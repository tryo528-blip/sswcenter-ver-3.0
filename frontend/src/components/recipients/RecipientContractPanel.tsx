import { useCallback, useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import {
  ApiError,
  createContract,
  listContracts,
  type ContractCreateRequest,
  type ContractResponse,
} from '../../services/w1dApi';

const SERVICE_TYPES = [
  'HOME_CARE',
  'HOME_BATH',
  'TEMP_HOME_CARE',
  'HOSPITAL_ESCORT',
  'BARO_CARE',
] as const;

type Props = {
  recipientId: number | string;
  recipientNo?: string | null;
  /** After successful contract create (including first-contract recipient_no). */
  onRecipientMutated?: () => void;
};

function emptyCreateDraft() {
  return {
    serviceType: 'HOME_CARE' as ContractCreateRequest['service_type_code'],
    startDate: '',
    endDate: '',
    serviceStartDate: '',
    endReason: '',
  };
}

function sameRecipient(a: number | string, b: number | string): boolean {
  return String(a) === String(b);
}

export default function RecipientContractPanel({
  recipientId,
  recipientNo,
  onRecipientMutated,
}: Props) {
  const [contracts, setContracts] = useState<ContractResponse[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [createDraft, setCreateDraft] = useState(emptyCreateDraft);
  const [saving, setSaving] = useState(false);

  // Ignore list and mutation completions that belong to a prior recipient.
  const loadGenerationRef = useRef(0);
  const activeRecipientRef = useRef(recipientId);

  const load = useCallback(async (forRecipientId: number | string) => {
    if (!sameRecipient(forRecipientId, activeRecipientRef.current)) return;
    const generation = ++loadGenerationRef.current;
    try {
      const data = await listContracts(forRecipientId);
      if (
        generation !== loadGenerationRef.current ||
        !sameRecipient(forRecipientId, activeRecipientRef.current)
      ) {
        return;
      }
      setContracts(data.items ?? []);
    } catch (requestError) {
      if (
        generation !== loadGenerationRef.current ||
        !sameRecipient(forRecipientId, activeRecipientRef.current)
      ) {
        return;
      }
      setError(
        requestError instanceof ApiError
          ? requestError.message
          : '계약을 불러오지 못했습니다.',
      );
    }
  }, []);

  useEffect(() => {
    activeRecipientRef.current = recipientId;
    loadGenerationRef.current += 1;
    setCreateDraft(emptyCreateDraft());
    setError(null);
    setSaving(false);
    setContracts([]);
    void load(recipientId);
  }, [recipientId, load]);

  const handleCreate = async (event: FormEvent) => {
    event.preventDefault();
    const opRecipientId = recipientId;
    setSaving(true);
    setError(null);
    try {
      await createContract(opRecipientId, {
        service_type_code: createDraft.serviceType,
        start_date: createDraft.startDate,
        end_date: createDraft.endDate || null,
        service_start_date: createDraft.serviceStartDate || null,
        end_reason_text: createDraft.endReason || null,
      });
      if (!sameRecipient(opRecipientId, activeRecipientRef.current)) return;
      setCreateDraft(emptyCreateDraft());
      await load(opRecipientId);
      if (!sameRecipient(opRecipientId, activeRecipientRef.current)) return;
      onRecipientMutated?.();
    } catch (requestError) {
      if (!sameRecipient(opRecipientId, activeRecipientRef.current)) return;
      setError(
        requestError instanceof ApiError
          ? requestError.message
          : '계약 생성에 실패했습니다.',
      );
    } finally {
      if (sameRecipient(opRecipientId, activeRecipientRef.current)) {
        setSaving(false);
      }
    }
  };

  return (
    <section
      className="recipient-subsection recipient-contract-section"
      data-testid="recipient-contract-panel"
    >
      <div className="recipient-subsection-heading">
        <h3>서비스 계약 (W1D)</h3>
        <span data-testid="contract-recipient-no-display">
          수급자번호: {recipientNo ?? '미발급'}
        </span>
      </div>
      {error ? (
        <div
          className="recipient-error"
          data-testid="contract-error"
          role="alert"
          aria-live="assertive"
        >
          {error}
        </div>
      ) : null}

      <form
        className="recipient-subform"
        data-testid="contract-create-form"
        onSubmit={handleCreate}
      >
        <div className="recipient-form-grid">
          <label className="recipient-field">
            서비스 유형 <em>필수</em>
            <select
              data-testid="contract-service-type-select"
              value={createDraft.serviceType}
              onChange={(event) =>
                setCreateDraft((current) => ({
                  ...current,
                  serviceType: event.target.value as ContractCreateRequest['service_type_code'],
                }))
              }
              required
              aria-required="true"
              disabled={saving}
            >
              {SERVICE_TYPES.map((code) => (
                <option key={code} value={code}>
                  {code}
                </option>
              ))}
            </select>
          </label>
          <label className="recipient-field">
            시작일 <em>필수</em>
            <input
              type="date"
              data-testid="contract-start-date-input"
              value={createDraft.startDate}
              onChange={(event) =>
                setCreateDraft((current) => ({ ...current, startDate: event.target.value }))
              }
              required
              aria-required="true"
              disabled={saving}
            />
          </label>
          <label className="recipient-field">
            종료일
            <input
              type="date"
              data-testid="contract-end-date-input"
              value={createDraft.endDate}
              onChange={(event) =>
                setCreateDraft((current) => ({ ...current, endDate: event.target.value }))
              }
              disabled={saving}
            />
          </label>
          <label className="recipient-field">
            급여개시일
            <input
              type="date"
              data-testid="contract-service-start-date-input"
              value={createDraft.serviceStartDate}
              onChange={(event) =>
                setCreateDraft((current) => ({
                  ...current,
                  serviceStartDate: event.target.value,
                }))
              }
              disabled={saving}
            />
          </label>
          <label className="recipient-field">
            종료 사유
            <input
              data-testid="contract-end-reason-input"
              value={createDraft.endReason}
              onChange={(event) =>
                setCreateDraft((current) => ({ ...current, endReason: event.target.value }))
              }
              disabled={saving}
            />
          </label>
        </div>
        <button
          type="submit"
          className="recipient-primary-button"
          data-testid="contract-new-button"
          disabled={saving}
        >
          새 계약
        </button>
      </form>

      <div className="recipient-history-list" data-testid="contract-list">
        {contracts.length ? (
          contracts.map((contract) => (
            <div
              className="recipient-history-card"
              key={contract.id}
              data-testid={`contract-row-${contract.id}`}
            >
              <strong>{contract.service_type_code}</strong>
              <span>
                {contract.start_date} ~ {contract.end_date ?? '진행중'}
              </span>
            </div>
          ))
        ) : (
          <div className="recipient-muted">등록된 계약이 없습니다.</div>
        )}
      </div>
    </section>
  );
}
