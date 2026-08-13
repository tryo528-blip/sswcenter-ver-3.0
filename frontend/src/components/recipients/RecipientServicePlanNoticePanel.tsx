import { useCallback, useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { ApiError } from '../../services/api';
import {
  W2ConflictError,
  createServicePlanNotice,
  listServicePlanNotices,
  replaceServicePlanNotice,
  type ServicePlanNotice,
} from '../../services/w2Api';
import { listContracts, type ContractResponse } from '../../services/w1dApi';

type Props = {
  recipientId: number | string;
};

type Draft = {
  contractId: string;
  notificationDate: string;
  appliedStartDate: string;
  appliedEndDate: string;
};

function todayText(): string {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Seoul',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date());
  const value = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return value.year && value.month && value.day
    ? `${value.year}-${value.month}-${value.day}`
    : '';
}

function emptyDraft(): Draft {
  return {
    contractId: '',
    notificationDate: todayText(),
    appliedStartDate: '',
    appliedEndDate: '',
  };
}

function sameRecipient(left: number | string, right: number | string): boolean {
  return String(left) === String(right);
}

function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError || error instanceof Error) return error.message || fallback;
  return fallback;
}

export default function RecipientServicePlanNoticePanel({ recipientId }: Props) {
  const [contracts, setContracts] = useState<ContractResponse[]>([]);
  const [history, setHistory] = useState<readonly ServicePlanNotice[]>([]);
  const [draft, setDraft] = useState<Draft>(emptyDraft);
  const [editing, setEditing] = useState<ServicePlanNotice | null>(null);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const activeRecipientRef = useRef(recipientId);
  const loadGenerationRef = useRef(0);

  const load = useCallback(async (forRecipientId: number | string) => {
    const generation = ++loadGenerationRef.current;
    setLoading(true);
    try {
      const [contractResponse, noticeResponse] = await Promise.all([
        listContracts(forRecipientId),
        listServicePlanNotices(forRecipientId),
      ]);
      if (
        generation !== loadGenerationRef.current
        || !sameRecipient(forRecipientId, activeRecipientRef.current)
      ) {
        return;
      }
      const availableContracts = (contractResponse.items ?? []).filter(
        (contract) => !contract.invalidated_at_utc,
      );
      setContracts(availableContracts);
      setHistory(noticeResponse.items);
      setDraft((current) => ({
        ...current,
        contractId: current.contractId || String(availableContracts[0]?.id ?? ''),
      }));
    } catch (requestError) {
      if (
        generation === loadGenerationRef.current
        && sameRecipient(forRecipientId, activeRecipientRef.current)
      ) {
        setError(errorMessage(requestError, '급여계획서 이력을 불러오지 못했습니다.'));
      }
    } finally {
      if (
        generation === loadGenerationRef.current
        && sameRecipient(forRecipientId, activeRecipientRef.current)
      ) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    activeRecipientRef.current = recipientId;
    loadGenerationRef.current += 1;
    setContracts([]);
    setHistory([]);
    setDraft(emptyDraft());
    setEditing(null);
    setSaving(false);
    setError(null);
    setMessage(null);
    void load(recipientId);
  }, [load, recipientId]);

  const cancelCorrection = () => {
    setEditing(null);
    setDraft({
      ...emptyDraft(),
      contractId: String(contracts[0]?.id ?? ''),
    });
    setError(null);
    setMessage(null);
  };

  const startCorrection = (notice: ServicePlanNotice) => {
    setEditing(notice);
    setDraft({
      contractId: String(notice.recipientContractId),
      notificationDate: notice.notificationDate,
      appliedStartDate: notice.appliedStartDate,
      appliedEndDate: notice.appliedEndDate,
    });
    setError(null);
    setMessage(null);
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (saving) return;
    const contractId = Number(draft.contractId);
    if (!Number.isSafeInteger(contractId) || contractId <= 0) {
      setError('연결할 서비스 계약을 선택해주세요.');
      return;
    }
    if (!draft.notificationDate || !draft.appliedStartDate) {
      setError('통보일과 적용 시작일을 입력해주세요.');
      return;
    }

    const operationRecipientId = recipientId;
    setSaving(true);
    setError(null);
    setMessage(null);
    const input = {
      recipientContractId: contractId,
      notificationDate: draft.notificationDate,
      appliedStartDate: draft.appliedStartDate,
      appliedEndDate: draft.appliedEndDate || null,
    };
    try {
      if (editing) {
        await replaceServicePlanNotice(
          operationRecipientId,
          editing.id,
          editing.rowVersion,
          input,
        );
      } else {
        await createServicePlanNotice(operationRecipientId, input);
      }
      if (!sameRecipient(operationRecipientId, activeRecipientRef.current)) return;
      setEditing(null);
      setDraft({ ...emptyDraft(), contractId: String(contracts[0]?.id ?? '') });
      setMessage(editing ? '급여계획서 이력을 정정했습니다.' : '급여계획서를 저장했습니다.');
      await load(operationRecipientId);
    } catch (requestError) {
      if (!sameRecipient(operationRecipientId, activeRecipientRef.current)) return;
      if (
        requestError instanceof W2ConflictError
        && requestError.latestServicePlanHistory
      ) {
        setHistory(requestError.latestServicePlanHistory.items);
        setError('다른 요청이 먼저 정정했습니다. 입력은 유지되며 최신 이력을 표시합니다.');
      } else {
        setError(errorMessage(requestError, '급여계획서를 저장하지 못했습니다.'));
      }
    } finally {
      if (sameRecipient(operationRecipientId, activeRecipientRef.current)) {
        setSaving(false);
      }
    }
  };

  return (
    <section
      className="recipient-subsection"
      data-testid="recipient-service-plan-notice-panel"
    >
      <div className="recipient-subsection-heading">
        <h3>급여계획서</h3>
      </div>

      {error ? <div className="recipient-inline-error" role="alert">{error}</div> : null}
      {message ? <div className="recipient-inline-note" role="status">{message}</div> : null}

      <form
        className="recipient-subform"
        data-testid="recipient-service-plan-notice-form"
        onSubmit={handleSubmit}
      >
        <div className="recipient-form-grid">
          <label className="recipient-field">
            서비스 계약 <em>필수</em>
            <select
              data-testid="service-plan-contract-select"
              value={draft.contractId}
              onChange={(event) => setDraft((current) => ({
                ...current,
                contractId: event.target.value,
              }))}
              required
              disabled={saving || loading}
            >
              <option value="">계약 선택</option>
              {contracts.map((contract) => (
                <option key={contract.id} value={contract.id}>
                  {contract.service_type_code} · {contract.start_date} ~ {contract.end_date ?? '진행중'}
                </option>
              ))}
            </select>
          </label>
          <label className="recipient-field">
            통보일 <em>필수</em>
            <input
              type="date"
              data-testid="service-plan-notification-date-input"
              value={draft.notificationDate}
              onChange={(event) => setDraft((current) => ({
                ...current,
                notificationDate: event.target.value,
              }))}
              required
              disabled={saving || loading}
            />
          </label>
          <label className="recipient-field">
            적용 시작일 <em>필수</em>
            <input
              type="date"
              data-testid="service-plan-applied-start-date-input"
              value={draft.appliedStartDate}
              onChange={(event) => setDraft((current) => ({
                ...current,
                appliedStartDate: event.target.value,
              }))}
              required
              disabled={saving || loading}
            />
          </label>
          <label className="recipient-field">
            적용 종료일
            <input
              type="date"
              data-testid="service-plan-applied-end-date-input"
              value={draft.appliedEndDate}
              onChange={(event) => setDraft((current) => ({
                ...current,
                appliedEndDate: event.target.value,
              }))}
              disabled={saving || loading}
            />
          </label>
        </div>
        <div className="recipient-history-card-actions">
          <button
            className="recipient-primary-button"
            type="submit"
            data-testid="service-plan-submit"
            disabled={saving || loading || contracts.length === 0}
          >
            {saving ? '저장 중…' : editing ? '정정 저장' : '계획서 저장'}
          </button>
          {editing ? (
            <button
              className="recipient-secondary-button"
              type="button"
              onClick={cancelCorrection}
              disabled={saving}
            >
              정정 취소
            </button>
          ) : null}
        </div>
      </form>

      <div className="recipient-history-list" data-testid="service-plan-history">
        {history.length ? history.map((notice) => (
          <div className="recipient-history-card" key={notice.id}>
            <strong>{notice.notificationDate}</strong>
            <span>{notice.appliedStartDate} ~ {notice.appliedEndDate}</span>
            <span>계약 #{notice.recipientContractId}</span>
            {notice.invalidatedAtUtc ? <span>정정 전 이력</span> : (
              <div className="recipient-history-card-actions">
                <button
                  type="button"
                  data-testid={`service-plan-correct-${notice.id}`}
                  onClick={() => startCorrection(notice)}
                  disabled={saving}
                >
                  정정
                </button>
              </div>
            )}
          </div>
        )) : (
          <div className="recipient-muted">
            {loading ? '급여계획서를 불러오는 중입니다.' : '등록된 급여계획서가 없습니다.'}
          </div>
        )}
      </div>
    </section>
  );
}
