import { useEffect, useMemo, useRef, type KeyboardEvent } from 'react';
import type {
  OfficialWorkCard,
  OfficialWorkCardCollection,
  OfficialWorkCardEligibleAssignee,
} from '../../services/w2Api';

export function formatOfficialDday(value: number): string {
  if (value === 0) return 'D-DAY';
  return value > 0 ? `D-${value}` : `D+${Math.abs(value)}`;
}

function officialWorkCardKindLabel(kind: OfficialWorkCard['kind']): string {
  const labels: Record<OfficialWorkCard['kind'], string> = {
    RECOGNITION_EXPIRY: '인정만료',
    CONTRACT_EXPIRY: '계약만료',
    PLAN_NOTICE: '계획서통보',
    STAFF_REPLACEMENT_CONSULTATION: '직원교체상담',
    NEW_STAFF_WORK: '신규직원업무',
  };
  return labels[kind];
}

function WorkCard({
  card,
  readOnly,
  canReassign,
  closing,
  reassigning,
  onClose,
  onReassign,
}: {
  card: OfficialWorkCard;
  readOnly: boolean;
  canReassign: boolean;
  closing: boolean;
  reassigning: boolean;
  onClose: (card: OfficialWorkCard) => void;
  onReassign: (card: OfficialWorkCard, trigger: HTMLButtonElement) => void;
}) {
  return (
    <article className="dashboard-official-card" data-testid="official-work-card">
      <dl className="dashboard-official-card-fields">
        <div><dt>업무제목</dt><dd>{card.title}</dd></div>
        <div><dt>대상자이름</dt><dd>{card.targetName || '미입력'}</dd></div>
        <div><dt>상세업무</dt><dd>{card.detail || '—'}</dd></div>
        <div><dt>마감일</dt><dd>{card.dueDate || '—'}</dd></div>
        <div><dt>D-day</dt><dd>{formatOfficialDday(card.dDay)}</dd></div>
      </dl>
      {(!readOnly || canReassign) && (
        <div className="dashboard-official-card-controls" aria-label="카드 제어">
          {canReassign && (
            <button
              type="button"
              data-testid="official-work-card-reassign"
              disabled={reassigning}
              onClick={(event) => onReassign(card, event.currentTarget)}
            >
              {reassigning ? '처리 중…' : '담당자 변경'}
            </button>
          )}
          {!readOnly && (
            <button type="button" disabled={closing} onClick={() => onClose(card)}>
              {closing ? '처리 중…' : '닫기'}
            </button>
          )}
        </div>
      )}
    </article>
  );
}

export function OfficialWorkCardReassignDialog({
  card,
  currentAssigneeName,
  eligibleAssignees,
  selectedStaffId,
  loading,
  submitting,
  error,
  onSelectedStaffIdChange,
  onCancel,
  onConfirm,
}: {
  card: OfficialWorkCard;
  currentAssigneeName: string;
  eligibleAssignees: readonly OfficialWorkCardEligibleAssignee[];
  selectedStaffId: number | '';
  loading: boolean;
  submitting: boolean;
  error: string | null;
  onSelectedStaffIdChange: (value: number | '') => void;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const dialogRef = useRef<HTMLElement>(null);
  const selectRef = useRef<HTMLSelectElement>(null);
  const cancelButtonRef = useRef<HTMLButtonElement>(null);
  const availableAssignees = useMemo(
    () => eligibleAssignees.filter((assignee) => assignee.staffId !== card.assigneeStaffId),
    [card.assigneeStaffId, eligibleAssignees],
  );
  const canConfirm = (
    !loading
    && !submitting
    && selectedStaffId !== ''
    && selectedStaffId !== card.assigneeStaffId
    && availableAssignees.some((assignee) => assignee.staffId === selectedStaffId)
  );

  useEffect(() => {
    if (!loading && availableAssignees.length > 0) {
      selectRef.current?.focus();
      return;
    }
    cancelButtonRef.current?.focus();
  }, [availableAssignees.length, loading]);

  const trapKeyboard = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      if (!submitting) onCancel();
      return;
    }
    if (event.key !== 'Tab') return;
    const focusable = Array.from(
      dialogRef.current?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), select:not([disabled]), [href]:not([aria-disabled="true"]), [tabindex]:not([tabindex="-1"])',
      ) ?? [],
    ).filter((element) => !element.hasAttribute('hidden'));
    if (focusable.length === 0) {
      event.preventDefault();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return (
    <div className="dashboard-official-reassign-backdrop" role="presentation">
      <section
        className="dashboard-official-reassign-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="official-work-card-reassign-title"
        data-testid="official-work-card-reassign-dialog"
        onKeyDown={trapKeyboard}
        ref={dialogRef}
      >
        <h2 id="official-work-card-reassign-title">담당자 변경 확인</h2>
        <dl className="dashboard-official-reassign-confirm">
          <div><dt>업무종류</dt><dd>{officialWorkCardKindLabel(card.kind)}</dd></div>
          <div><dt>대상자</dt><dd>{card.targetName || '미입력'}</dd></div>
          <div><dt>상세업무</dt><dd>{card.detail}</dd></div>
          <div><dt>마감일</dt><dd>{card.dueDate}</dd></div>
          <div><dt>현재 담당자</dt><dd>{currentAssigneeName || '미입력'}</dd></div>
        </dl>
        <label className="dashboard-official-reassign-label" htmlFor="official-work-card-new-assignee">
          새 담당자
        </label>
        <select
          id="official-work-card-new-assignee"
          data-testid="official-work-card-new-assignee"
          aria-busy={loading}
          ref={selectRef}
          value={selectedStaffId === '' ? '' : String(selectedStaffId)}
          disabled={submitting || loading || availableAssignees.length === 0}
          onChange={(event) => {
            onSelectedStaffIdChange(
              event.target.value === '' ? '' : Number(event.target.value),
            );
          }}
        >
          <option value="">담당자를 선택하세요</option>
          {availableAssignees.map((assignee) => (
            <option key={assignee.staffId} value={assignee.staffId}>
              {assignee.staffName}
            </option>
          ))}
        </select>
        {loading && <p className="dashboard-official-reassign-loading" role="status">담당자 목록을 불러오는 중입니다.</p>}
        {!loading && availableAssignees.length === 0 && !error && (
          <p className="dashboard-official-reassign-error" role="alert">배정 가능한 담당자가 없습니다.</p>
        )}
        {error && <p className="dashboard-official-reassign-error" role="alert">{error}</p>}
        <div className="dashboard-official-reassign-actions">
          <button ref={cancelButtonRef} type="button" disabled={submitting} onClick={onCancel}>취소</button>
          <button
            type="button"
            data-testid="official-work-card-reassign-confirm"
            disabled={!canConfirm}
            onClick={onConfirm}
          >
            {submitting ? '처리 중…' : '담당자 변경'}
          </button>
        </div>
      </section>
    </div>
  );
}

export function OfficialWorkCards({
  collection,
  readOnly,
  showStaffGroups,
  canReassign,
  closingId,
  reassigningId,
  onClose,
  onReassign,
}: {
  collection: OfficialWorkCardCollection;
  readOnly: boolean;
  showStaffGroups: boolean;
  canReassign: boolean;
  closingId: number | null;
  reassigningId: number | null;
  onClose: (card: OfficialWorkCard) => void;
  onReassign: (card: OfficialWorkCard, trigger: HTMLButtonElement) => void;
}) {
  const cardCount = collection.groups.reduce((sum, group) => sum + group.cards.length, 0);

  return (
    <section className="dashboard-work-block" aria-label="공식 업무카드">
      <div className="dashboard-work-heading">
        <h2>공식 업무카드</h2>
      </div>
      {cardCount === 0 ? (
        <p className="dashboard-work-empty">열린 업무카드가 없습니다.</p>
      ) : (
        <div className="dashboard-official-groups">
          {collection.groups.map((group, groupIndex) => (
            <section className="dashboard-official-group" key={`${group.staffId}-${groupIndex}`}>
              {showStaffGroups && (
                <h3 className="dashboard-official-staff-name">{group.staffName || '미입력'}</h3>
              )}
              <div className="dashboard-work-area">
                {group.cards.map((card) => (
                  <WorkCard
                    card={card}
                    canReassign={canReassign}
                    closing={closingId === card.id}
                    key={card.id}
                    onClose={onClose}
                    onReassign={onReassign}
                    readOnly={readOnly}
                    reassigning={reassigningId === card.id}
                  />
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </section>
  );
}
