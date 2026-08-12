import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import {
  ApiError,
  applyCertificationTransition,
  createContract,
  listContracts,
  previewCertificationTransition,
  type ContractCreateRequest,
  type ContractResponse,
  type TransitionPreviewRequest,
  type TransitionPreviewResponse,
  type TransitionReplacementItem,
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
  /** After successful contract create (incl. first-contract recipient_no). */
  onRecipientMutated?: () => void;
};

function emptyCreateDraft() {
  return {
    serviceType: 'HOME_CARE' as ContractCreateRequest['service_type_code'],
    startDate: '',
    endDate: '',
    serviceStartDate: '',
    signerName: '',
    signerRelationship: '',
    signerPhone: '',
    endReason: '',
  };
}

function emptyTransitionDraft() {
  return {
    newStart: '',
    newEnd: '',
    newGrade: '4' as TransitionPreviewRequest['new_grade_code'],
    newGradeStart: '',
    newGradeEnd: '',
  };
}

function sameRecipient(
  a: number | string,
  b: number | string,
): boolean {
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

  const [transition, setTransition] = useState(emptyTransitionDraft);
  const [preview, setPreview] = useState<TransitionPreviewResponse | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [stale, setStale] = useState(false);
  const [applying, setApplying] = useState(false);
  const [boundReplacements, setBoundReplacements] = useState<
    TransitionReplacementItem[]
  >([]);

  // Ignore in-flight list responses after recipient switch.
  const loadGenerationRef = useRef(0);
  // Invalidate in-flight preview after input edit / new preview / recipient switch.
  const previewGenerationRef = useRef(0);
  // Identifies the apply request that owns the duplicate-submit guard. A
  // recipient switch invalidates the owner so a late old request cannot clear
  // a newer recipient's guard.
  const applyOperationRef = useRef(0);
  const applyingRef = useRef(false);
  const activeRecipientRef = useRef(recipientId);

  const discardPreview = useCallback(() => {
    setPreview(null);
    setConfirmed(false);
    setBoundReplacements([]);
  }, []);

  const discardPreviewAndStale = useCallback(() => {
    discardPreview();
    setStale(false);
  }, [discardPreview]);

  /** Token-contributing transition fields: any edit drops preview/confirm/bound/stale
   *  and invalidates any in-flight preview generation. */
  const updateTransitionField = useCallback(
    <K extends keyof ReturnType<typeof emptyTransitionDraft>>(
      key: K,
      value: ReturnType<typeof emptyTransitionDraft>[K],
    ) => {
      setTransition((current) => ({ ...current, [key]: value }));
      previewGenerationRef.current += 1;
      discardPreviewAndStale();
    },
    [discardPreviewAndStale],
  );

  const load = useCallback(async (forRecipientId: number | string) => {
    // Reject inactive recipient IDs before advancing generation so a late
    // create/apply completion for an old recipient cannot invalidate the
    // active recipient's in-flight list load.
    if (!sameRecipient(forRecipientId, activeRecipientRef.current)) {
      return;
    }
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
    } catch (err) {
      if (
        generation !== loadGenerationRef.current ||
        !sameRecipient(forRecipientId, activeRecipientRef.current)
      ) {
        return;
      }
      setError(err instanceof ApiError ? err.message : '계약을 불러오지 못했습니다.');
    }
  }, []);

  // Recipient switch: reset drafts/state, then load contracts for the new id.
  useEffect(() => {
    activeRecipientRef.current = recipientId;
    loadGenerationRef.current += 1;
    previewGenerationRef.current += 1;
    setCreateDraft(emptyCreateDraft());
    setTransition(emptyTransitionDraft());
    discardPreviewAndStale();
    setError(null);
    setSaving(false);
    applyOperationRef.current += 1;
    applyingRef.current = false;
    setApplying(false);
    setContracts([]);
    void load(recipientId);
  }, [recipientId, load, discardPreviewAndStale]);

  const applyDisabled = useMemo(
    () => !preview || !confirmed || stale || applying,
    [preview, confirmed, stale, applying],
  );
  const previewDisabled = useMemo(
    () =>
      !transition.newStart ||
      !transition.newEnd ||
      !transition.newGrade ||
      !transition.newGradeStart ||
      !transition.newGradeEnd,
    [transition],
  );

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
        signer_name: createDraft.signerName || null,
        signer_relationship_text: createDraft.signerRelationship || null,
        signer_phone: createDraft.signerPhone || null,
        end_reason_text: createDraft.endReason || null,
      });
      // Backend mutation already completed; only update panel for still-active recipient.
      if (!sameRecipient(opRecipientId, activeRecipientRef.current)) {
        return;
      }
      setCreateDraft(emptyCreateDraft());
      await load(opRecipientId);
      if (!sameRecipient(opRecipientId, activeRecipientRef.current)) {
        return;
      }
      onRecipientMutated?.();
    } catch (err) {
      if (!sameRecipient(opRecipientId, activeRecipientRef.current)) {
        return;
      }
      setError(err instanceof ApiError ? err.message : '계약 생성에 실패했습니다.');
    } finally {
      if (sameRecipient(opRecipientId, activeRecipientRef.current)) {
        setSaving(false);
      }
    }
  };

  const handlePreview = async () => {
    if (previewDisabled) return;
    const opRecipientId = recipientId;
    // Allocate generation first, then drop any already-resolved preview/token/
    // confirmation/bound set so the user cannot re-confirm and apply an old
    // token while a newer preview is in flight.
    const generation = ++previewGenerationRef.current;
    setError(null);
    setStale(false);
    discardPreview();
    try {
      const openLtc = contracts.filter(
        (c) =>
          c.end_date == null &&
          c.invalidated_at_utc == null &&
          c.service_group_code === 'LONG_TERM_CARE',
      );
      const replacements: TransitionReplacementItem[] = openLtc.map((c) => ({
        ended_contract_id: c.id,
        service_type_code:
          c.service_type_code as TransitionReplacementItem['service_type_code'],
        start_date: transition.newStart,
        end_date: null,
        service_start_date: null,
        signer_name: null,
        signer_relationship_text: null,
        signer_phone: null,
        end_reason_text: null,
      }));
      const body: TransitionPreviewRequest = {
        new_start_date: transition.newStart,
        new_end_date: transition.newEnd,
        new_grade_code: transition.newGrade,
        new_grade_start_date: transition.newGradeStart,
        new_grade_end_date: transition.newGradeEnd,
        replacement_contracts: replacements,
      };
      const result = await previewCertificationTransition(opRecipientId, body);
      if (
        generation !== previewGenerationRef.current ||
        !sameRecipient(opRecipientId, activeRecipientRef.current)
      ) {
        return;
      }
      setPreview(result);
      setBoundReplacements(replacements);
    } catch (err) {
      // Old failed request must not clear/set state for a newer generation.
      if (
        generation !== previewGenerationRef.current ||
        !sameRecipient(opRecipientId, activeRecipientRef.current)
      ) {
        return;
      }
      discardPreview();
      setError(err instanceof ApiError ? err.message : '미리보기에 실패했습니다.');
    }
  };

  const handleApply = async () => {
    if (!preview || !confirmed || stale || applyingRef.current) return;
    const applyOperation = ++applyOperationRef.current;
    applyingRef.current = true;
    setApplying(true);
    const opRecipientId = recipientId;
    // Capture token A and allocate a generation so a later same-recipient
    // preview B / input edit / recipient switch / newer apply invalidates A
    // for UI state (backend mutation may still complete).
    const applyToken = preview.preview_token;
    const applyGeneration = ++previewGenerationRef.current;
    const applyBound = boundReplacements;
    setError(null);

    const applyUiStillCurrent = () =>
      sameRecipient(opRecipientId, activeRecipientRef.current) &&
      applyGeneration === previewGenerationRef.current;

    try {
      await applyCertificationTransition(opRecipientId, {
        preview_token: applyToken,
        confirmed: true,
        replacement_contracts: applyBound,
      });
      // Backend apply already completed; panel state only if still current.
      if (!applyUiStillCurrent()) {
        return;
      }
      discardPreview();
      setStale(false);
      await load(opRecipientId);
    } catch (err) {
      if (!applyUiStillCurrent()) {
        return;
      }
      const code =
        err instanceof ApiError
          ? String((err as ApiError & { code?: string }).code ?? err.message)
          : '';
      if (code.includes('STALE') || (err instanceof ApiError && err.status === 409)) {
        setStale(true);
        discardPreview();
      } else {
        discardPreview();
        setError(err instanceof ApiError ? err.message : '전환 적용에 실패했습니다.');
      }
    } finally {
      if (applyOperation === applyOperationRef.current) {
        applyingRef.current = false;
        if (sameRecipient(opRecipientId, activeRecipientRef.current)) {
          setApplying(false);
        }
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
              onChange={(e) =>
                setCreateDraft((c) => ({
                  ...c,
                  serviceType:
                    e.target.value as ContractCreateRequest['service_type_code'],
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
              onChange={(e) =>
                setCreateDraft((c) => ({ ...c, startDate: e.target.value }))
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
              onChange={(e) =>
                setCreateDraft((c) => ({ ...c, endDate: e.target.value }))
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
              onChange={(e) =>
                setCreateDraft((c) => ({
                  ...c,
                  serviceStartDate: e.target.value,
                }))
              }
              disabled={saving}
            />
          </label>
          <label className="recipient-field">
            서명자 이름
            <input
              data-testid="contract-signer-name-input"
              value={createDraft.signerName}
              onChange={(e) =>
                setCreateDraft((c) => ({ ...c, signerName: e.target.value }))
              }
              disabled={saving}
            />
          </label>
          <label className="recipient-field">
            서명자 관계
            <input
              data-testid="contract-signer-relationship-input"
              value={createDraft.signerRelationship}
              onChange={(e) =>
                setCreateDraft((c) => ({
                  ...c,
                  signerRelationship: e.target.value,
                }))
              }
              disabled={saving}
            />
          </label>
          <label className="recipient-field">
            서명자 전화
            <input
              data-testid="contract-signer-phone-input"
              value={createDraft.signerPhone}
              onChange={(e) =>
                setCreateDraft((c) => ({ ...c, signerPhone: e.target.value }))
              }
              disabled={saving}
            />
          </label>
          <label className="recipient-field">
            종료 사유
            <input
              data-testid="contract-end-reason-input"
              value={createDraft.endReason}
              onChange={(e) =>
                setCreateDraft((c) => ({ ...c, endReason: e.target.value }))
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
          contracts.map((c) => (
            <div
              className="recipient-history-card"
              key={c.id}
              data-testid={`contract-row-${c.id}`}
            >
              <strong>{c.service_type_code}</strong>
              <span>
                {c.start_date} ~ {c.end_date ?? '진행중'}
              </span>
            </div>
          ))
        ) : (
          <div className="recipient-muted">등록된 계약이 없습니다.</div>
        )}
      </div>

      <section
        className="recipient-subsection"
        data-testid="certification-transition-panel"
      >
        <div className="recipient-subsection-heading">
          <h3>인정 전환</h3>
        </div>
        {stale ? (
          <div
            className="recipient-error"
            data-testid="transition-stale-banner"
            role="alert"
            aria-live="assertive"
          >
            상태가 변경되었습니다. 다시 미리보세요.
          </div>
        ) : null}
        <div className="recipient-form-grid">
          <label className="recipient-field">
            새 인정 시작 <em>필수</em>
            <input
              type="date"
              data-testid="transition-new-start-date"
              value={transition.newStart}
              onChange={(e) => updateTransitionField('newStart', e.target.value)}
              required
              aria-required="true"
            />
          </label>
          <label className="recipient-field">
            새 인정 종료 <em>필수</em>
            <input
              type="date"
              data-testid="transition-new-end-date"
              value={transition.newEnd}
              onChange={(e) => updateTransitionField('newEnd', e.target.value)}
              required
              aria-required="true"
            />
          </label>
          <label className="recipient-field">
            새 등급 <em>필수</em>
            <select
              data-testid="transition-new-grade-code"
              value={transition.newGrade}
              onChange={(e) =>
                updateTransitionField(
                  'newGrade',
                  e.target.value as TransitionPreviewRequest['new_grade_code'],
                )
              }
              required
              aria-required="true"
            >
              {['1', '2', '3', '4', '5'].map((g) => (
                <option key={g} value={g}>
                  {g}
                </option>
              ))}
            </select>
          </label>
          <label className="recipient-field">
            등급 시작 <em>필수</em>
            <input
              type="date"
              data-testid="transition-new-grade-start-date"
              value={transition.newGradeStart}
              onChange={(e) =>
                updateTransitionField('newGradeStart', e.target.value)
              }
              required
              aria-required="true"
            />
          </label>
          <label className="recipient-field">
            등급 종료 <em>필수</em>
            <input
              type="date"
              data-testid="transition-new-grade-end-date"
              value={transition.newGradeEnd}
              onChange={(e) =>
                updateTransitionField('newGradeEnd', e.target.value)
              }
              required
              aria-required="true"
            />
          </label>
        </div>
        <button
          type="button"
          className="recipient-secondary-button"
          data-testid="transition-preview-button"
          disabled={previewDisabled}
          onClick={() => void handlePreview()}
        >
          미리보기
        </button>
        {preview ? (
          <>
            <div data-testid="transition-impact-list">
              <div data-testid="transition-affected-certification-ids">
                종료 인정: {preview.affected_certification_period_ids.join(', ')}
              </div>
              <div data-testid="transition-affected-grade-ids">
                종료 등급: {preview.affected_grade_period_ids.join(', ')}
              </div>
              <div data-testid="transition-affected-contract-ids">
                종료 계약: {preview.affected_contract_ids.join(', ')}
              </div>
            </div>
            <div data-testid="transition-service-multiset">
              서비스: {preview.service_multiset.join(', ')}
            </div>
            <div data-testid="transition-proposed-end-date">
              제안 종료일: {preview.proposed_end_date}
            </div>
          </>
        ) : null}
        <label className="recipient-field">
          <input
            type="checkbox"
            data-testid="transition-confirm-checkbox"
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
            disabled={!preview || stale || applying}
          />{' '}
          전환을 확인합니다
        </label>
        <button
          type="button"
          className="recipient-primary-button"
          data-testid="transition-apply-button"
          disabled={applyDisabled}
          onClick={() => void handleApply()}
        >
          {applying ? '적용 중…' : '전환 적용'}
        </button>
      </section>
    </section>
  );
}
