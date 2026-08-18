import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { EditorialCard, EditorialPage } from '../components/common/EditorialPage';
import {
  ApiError,
  applyW3ImportRun,
  confirmW3ImportRun,
  getW3Workspace,
  latestW3WorkspaceFromError,
  newW3CommandKey,
  resolveW3MatchDecision,
  uploadW3Workbook,
  type W3DecisionItem,
  type W3ResolveDecisionInput,
  type W3RunStatus,
  type W3SourceType,
  type W3WorkspaceResponse,
} from '../services/w3Api';

const SINGLE_STATEFUL_WORKSPACE = 'W3_FILE_ONLY_SINGLE_STATEFUL_WORKSPACE';

const SOURCE_LABELS: Record<W3SourceType, string> = {
  NHIS_SCHEDULE: '공단 급여계획',
  RFID: 'RFID 실제근무',
};

const STATUS_LABELS: Record<W3RunStatus, string> = {
  RECEIVED: '수신됨',
  PARSING: '분석 중',
  PREVIEW_READY: '미리보기 준비',
  CONFIRMED: '확인 완료',
  APPLYING: '적용 중',
  APPLIED: '적용 완료',
  BLOCKED: '차단됨',
  FAILED: '실패',
};

const EMPTY_LINK = {
  recipient_id: '',
  certification_period_id: '',
  staff_id: '',
  employment_id: '',
  service_type_id: '',
  recipient_contract_id: '',
  care_assignment_id: '',
  w2_schedule_id: '',
};

type ManualLinkDraft = typeof EMPTY_LINK;
type ManualLinkKey = keyof ManualLinkDraft;

const MANUAL_LINK_FIELDS: readonly [ManualLinkKey, string][] = [
  ['recipient_id', '수급자 ID'],
  ['certification_period_id', '인정기간 ID'],
  ['staff_id', '직원 ID'],
  ['employment_id', '재직 ID'],
  ['service_type_id', '서비스유형 ID'],
  ['recipient_contract_id', '계약 ID'],
  ['care_assignment_id', '배정 ID'],
  ['w2_schedule_id', '일정 ID'],
];

function localDateValue(): string {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

function formatTimestamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('ko-KR', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return '요청을 처리하지 못했습니다.';
}

function toPositiveInteger(value: string): number | null {
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
}

function runSummaryText(workspace: W3WorkspaceResponse | null): string {
  if (!workspace?.latest_run) return '아직 이 날짜에 업로드한 파일이 없습니다.';
  const run = workspace.latest_run;
  return `${SOURCE_LABELS[run.source_type]} · ${run.original_filename} · ${STATUS_LABELS[run.status]}`;
}

export const IOPage = () => {
  const [sourceType, setSourceType] = useState<W3SourceType>('RFID');
  const [targetDate, setTargetDate] = useState(localDateValue);
  const [file, setFile] = useState<File | null>(null);
  const [fileInputKey, setFileInputKey] = useState(0);
  const [workspace, setWorkspace] = useState<W3WorkspaceResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedDecisionId, setSelectedDecisionId] = useState<number | null>(null);
  const [manualLink, setManualLink] = useState<ManualLinkDraft>({ ...EMPTY_LINK });
  const commandKeys = useRef<Record<string, string>>({});

  const loadWorkspace = useCallback(async (signal?: AbortSignal) => {
    setIsLoading(true);
    setError(null);
    try {
      const next = await getW3Workspace(sourceType, targetDate, signal);
      setWorkspace(next);
    } catch (requestError) {
      if (requestError instanceof Error && requestError.name === 'AbortError') return;
      setError(errorMessage(requestError));
    } finally {
      if (!signal?.aborted) setIsLoading(false);
    }
  }, [sourceType, targetDate]);

  useEffect(() => {
    const controller = new AbortController();
    void loadWorkspace(controller.signal);
    return () => controller.abort();
  }, [loadWorkspace]);

  const latestRun = workspace?.latest_run ?? null;
  const reviewDecisions = useMemo(
    () => latestRun?.decisions.filter(
      (item) => item.status === 'REVIEW_PENDING' || item.status === 'BLOCKED',
    ) ?? [],
    [latestRun],
  );
  const selectedDecision = latestRun?.decisions.find(
    (item) => item.id === selectedDecisionId,
  ) ?? null;

  function keyFor(action: string): string {
    commandKeys.current[action] ??= newW3CommandKey(action);
    return commandKeys.current[action];
  }

  async function runCommand(
    action: string,
    command: (key: string) => Promise<W3WorkspaceResponse>,
    successMessage: string,
  ): Promise<boolean> {
    if (busyAction) return false;
    setBusyAction(action);
    setError(null);
    setNotice(null);
    try {
      const next = await command(keyFor(action));
      delete commandKeys.current[action];
      setWorkspace(next);
      setNotice(successMessage);
      return true;
    } catch (requestError) {
      const latest = latestW3WorkspaceFromError(requestError);
      if (latest) setWorkspace(latest);
      setError(errorMessage(requestError));
      return false;
    } finally {
      setBusyAction(null);
    }
  }

  async function handleUpload(): Promise<void> {
    if (!file) {
      setError('업로드할 .xlsx 파일을 선택하세요.');
      return;
    }
    const succeeded = await runCommand(
      `upload-${sourceType}-${targetDate}-${file.name}-${file.size}`,
      () => uploadW3Workbook({ sourceType, targetDate, file }),
      '파일 분석이 끝났습니다. 미리보기 내용을 확인하세요.',
    );
    if (succeeded) {
      setFile(null);
      setFileInputKey((value) => value + 1);
    }
  }

  async function handleConfirm(): Promise<void> {
    if (!latestRun) return;
    await runCommand(
      `confirm-${latestRun.id}`,
      (key) => confirmW3ImportRun(latestRun, key),
      '미리보기를 확인했습니다. 이제 업무자료에 적용할 수 있습니다.',
    );
  }

  async function handleApply(): Promise<void> {
    if (!latestRun) return;
    await runCommand(
      `apply-${latestRun.id}`,
      (key) => applyW3ImportRun(latestRun, key),
      '업무자료 적용이 완료되었습니다.',
    );
  }

  async function handleResolve(decision: W3DecisionItem): Promise<void> {
    if (!latestRun) return;
    const parsedEntries = MANUAL_LINK_FIELDS.map(([key]) => [
      key,
      toPositiveInteger(manualLink[key]),
    ] as const);
    if (parsedEntries.some(([, value]) => value === null)) {
      setError('수동 연결의 모든 ID를 1 이상의 정수로 입력하세요.');
      return;
    }
    const input = Object.fromEntries(parsedEntries) as unknown as Omit<
      W3ResolveDecisionInput,
      'expected_run_row_version'
    >;
    await runCommand(
      `resolve-${latestRun.id}-${decision.id}`,
      (key) => resolveW3MatchDecision(
        latestRun.id,
        decision.id,
        { ...input, expected_run_row_version: latestRun.row_version },
        key,
      ),
      '검토 항목을 수동 연결했습니다.',
    );
  }

  const targetInputValue = sourceType === 'NHIS_SCHEDULE'
    ? targetDate.slice(0, 7)
    : targetDate;
  const isBusy = busyAction !== null;

  return (
    <EditorialPage
      testId="page-io"
      className="io-page"
      eyebrow="FILE ONLY"
      title="입출력"
      description="파일을 올리고, 검토하고, 확인한 뒤 업무자료에 적용합니다."
    >
      <div data-workspace-contract={SINGLE_STATEFUL_WORKSPACE}>
        <EditorialCard
          title="자료 선택"
          caption="원본 파일은 비공개 저장소에 보관되고 화면에는 업무상 필요한 결과만 표시됩니다."
        >
          <div className="io-upload-grid">
            <label className="io-field">
              <span>자료 종류</span>
              <select
                value={sourceType}
                disabled={isBusy}
                onChange={(event) => {
                  const next = event.target.value as W3SourceType;
                  setSourceType(next);
                  if (next === 'NHIS_SCHEDULE') {
                    setTargetDate((value) => `${value.slice(0, 7)}-01`);
                  }
                  setSelectedDecisionId(null);
                  setNotice(null);
                }}
              >
                <option value="NHIS_SCHEDULE">공단 급여계획</option>
                <option value="RFID">RFID 실제근무</option>
              </select>
            </label>
            <label className="io-field">
              <span>{sourceType === 'NHIS_SCHEDULE' ? '대상 월' : '대상 일자'}</span>
              <input
                type={sourceType === 'NHIS_SCHEDULE' ? 'month' : 'date'}
                value={targetInputValue}
                disabled={isBusy}
                onChange={(event) => setTargetDate(
                  sourceType === 'NHIS_SCHEDULE'
                    ? `${event.target.value}-01`
                    : event.target.value,
                )}
              />
            </label>
            <label className="io-field io-file-field">
              <span>엑셀 파일</span>
              <input
                key={fileInputKey}
                type="file"
                accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                disabled={isBusy}
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              />
            </label>
            <button
              type="button"
              className="editorial-primary-button io-upload-button"
              disabled={isBusy || !file}
              onClick={() => void handleUpload()}
            >
              {busyAction?.startsWith('upload-') ? '분석 중…' : '파일 분석'}
            </button>
          </div>
        </EditorialCard>

        {error ? <p className="io-banner io-banner-error" role="alert">{error}</p> : null}
        {notice ? <p className="io-banner io-banner-success" role="status">{notice}</p> : null}

        <EditorialCard
          title="현재 작업"
          caption={isLoading ? '최신 상태를 불러오는 중입니다.' : runSummaryText(workspace)}
          action={(
            <button
              type="button"
              className="editorial-text-button"
              disabled={isLoading || isBusy}
              onClick={() => void loadWorkspace()}
            >
              새로고침
            </button>
          )}
          className="io-current-card"
        >
          {!isLoading && !latestRun ? (
            <p className="io-empty">선택한 날짜의 파일을 올리면 미리보기가 여기에 표시됩니다.</p>
          ) : null}

          {latestRun ? (
            <>
              {workspace?.active ? (
                <div className="io-active-snapshot" role="status">
                  <strong>현재 적용본</strong>
                  <span>스냅샷 #{workspace.active.snapshot_id}</span>
                  <span>실행 #{workspace.active.import_run_id}</span>
                  <span>제어 버전 {workspace.active.row_version}</span>
                </div>
              ) : (
                <p className="io-active-empty">아직 이 날짜에 적용된 업무자료가 없습니다.</p>
              )}
              <div className="io-count-grid" aria-label="분석 결과 집계">
                <div><span>원본 행</span><strong>{latestRun.counts.raw_rows}</strong></div>
                <div><span>정규화</span><strong>{latestRun.counts.normalized_rows}</strong></div>
                <div><span>대상 자료</span><strong>{latestRun.counts.target_rows}</strong></div>
                <div><span>자동 연결</span><strong>{latestRun.counts.auto_matches}</strong></div>
                <div><span>수동 연결</span><strong>{latestRun.counts.manual_matches}</strong></div>
                <div className={latestRun.counts.review_pending ? 'io-count-warning' : ''}>
                  <span>검토 필요</span><strong>{latestRun.counts.review_pending}</strong>
                </div>
                <div className={latestRun.counts.blocked ? 'io-count-danger' : ''}>
                  <span>차단</span><strong>{latestRun.counts.blocked}</strong>
                </div>
              </div>

              {latestRun.warning_codes.length > 0 ? (
                <div className="io-warning-list">
                  <strong>확인할 경고</strong>
                  <ul>{latestRun.warning_codes.map((code) => <li key={code}>{code}</li>)}</ul>
                </div>
              ) : null}

              <div className="io-action-row">
                <div>
                  <span className={`io-status io-status-${latestRun.status.toLowerCase()}`}>
                    {STATUS_LABELS[latestRun.status]}
                  </span>
                  {latestRun.counts.review_pending > 0 ? (
                    <small>검토 항목을 모두 연결해야 확인할 수 있습니다.</small>
                  ) : null}
                </div>
                <div className="io-action-buttons">
                  <button
                    type="button"
                    className="editorial-primary-button"
                    disabled={isBusy || !latestRun.can_confirm || latestRun.counts.review_pending > 0}
                    onClick={() => void handleConfirm()}
                  >
                    {busyAction === `confirm-${latestRun.id}` ? '확인 중…' : '미리보기 확인'}
                  </button>
                  <button
                    type="button"
                    className="editorial-primary-button io-apply-button"
                    disabled={isBusy || !latestRun.can_apply}
                    onClick={() => void handleApply()}
                  >
                    {busyAction === `apply-${latestRun.id}` ? '적용 중…' : '업무자료 적용'}
                  </button>
                </div>
              </div>
            </>
          ) : null}
        </EditorialCard>

        {latestRun && reviewDecisions.length > 0 ? (
          <EditorialCard
            title="연결 검토"
            caption="자동으로 하나를 확정할 수 없는 항목만 표시합니다. 실제 업무자료의 ID를 모두 확인해 연결하세요."
            className="io-review-card"
          >
            <div className="io-table-scroll">
              <table className="editorial-table io-review-table">
                <thead>
                  <tr><th>행</th><th>일자</th><th>서비스</th><th>전송상태</th><th>사유</th><th>처리</th></tr>
                </thead>
                <tbody>
                  {reviewDecisions.map((decision) => (
                    <tr key={decision.id} data-selected={decision.id === selectedDecisionId}>
                      <td>{decision.source_row_number ?? '묶음'}</td>
                      <td>{decision.service_date}</td>
                      <td>{decision.service_category}</td>
                      <td>{decision.end_display ?? decision.event_state ?? '-'}</td>
                      <td>{decision.reason_code}</td>
                      <td>
                        <button
                          type="button"
                          className="editorial-text-button"
                          disabled={isBusy || latestRun.status !== 'PREVIEW_READY'}
                          onClick={() => {
                            setSelectedDecisionId(decision.id);
                            setManualLink({ ...EMPTY_LINK });
                          }}
                        >
                          연결 입력
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {selectedDecision ? (
              <form
                className="io-resolution-form"
                aria-label="수동 연결 입력"
                onSubmit={(event) => {
                  event.preventDefault();
                  void handleResolve(selectedDecision);
                }}
              >
                <div className="io-resolution-heading">
                  <strong>검토 항목 #{selectedDecision.id} 연결</strong>
                  <button
                    type="button"
                    className="editorial-text-button"
                    onClick={() => setSelectedDecisionId(null)}
                  >
                    닫기
                  </button>
                </div>
                <div className="io-resolution-grid">
                  {MANUAL_LINK_FIELDS.map(([key, label]) => (
                    <label className="io-field" key={key}>
                      <span>{label}</span>
                      <input
                        type="number"
                        min="1"
                        step="1"
                        required
                        value={manualLink[key]}
                        disabled={isBusy}
                        onChange={(event) => setManualLink((current) => ({
                          ...current,
                          [key]: event.target.value,
                        }))}
                      />
                    </label>
                  ))}
                </div>
                <button
                  type="submit"
                  className="editorial-primary-button"
                  disabled={isBusy || latestRun.status !== 'PREVIEW_READY'}
                >
                  {busyAction === `resolve-${latestRun.id}-${selectedDecision.id}`
                    ? '연결 중…'
                    : '수동 연결 저장'}
                </button>
              </form>
            ) : null}
          </EditorialCard>
        ) : null}

        {workspace && workspace.recent_runs.length > 0 ? (
          <EditorialCard title="최근 실행" caption="같은 자료종류와 대상일자의 최근 10건입니다.">
            <div className="io-table-scroll">
              <table className="editorial-table">
                <thead><tr><th>파일</th><th>시각</th><th>상태</th><th>검토</th><th>적용</th></tr></thead>
                <tbody>
                  {workspace.recent_runs.map((run) => (
                    <tr key={run.id}>
                      <td>{run.original_filename}</td>
                      <td>{formatTimestamp(run.created_at_utc)}</td>
                      <td>{STATUS_LABELS[run.status]}</td>
                      <td>{run.counts.review_pending + run.counts.blocked}</td>
                      <td>{run.status === 'APPLIED' ? '완료' : '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </EditorialCard>
        ) : null}
      </div>
    </EditorialPage>
  );
};

export default IOPage;
