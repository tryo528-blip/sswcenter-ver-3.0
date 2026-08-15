import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { ApiError } from '../../services/api';
import {
  createCareAssignment,
  listCareAssignments,
  replaceCareAssignment,
  type AssignmentKind,
  type CareAssignment,
  type CareAssignmentCreateRequest,
  type CareAssignmentReplaceRequest,
} from '../../services/careAssignmentApi';
import { fetchStaffPage, type StaffResponse } from '../../services/staffApi';
import {
  listContracts,
  type ContractResponse,
} from '../../services/w1dApi';

type Props = {
  recipientId: number | string;
};

type Draft = {
  staffKey: string;
  assignmentKind: AssignmentKind;
  familyRelationshipText: string;
  startDate: string;
  endDate: string;
};

const EMPTY_DRAFT: Draft = {
  staffKey: '',
  assignmentKind: 'GENERAL',
  familyRelationshipText: '',
  startDate: '',
  endDate: '',
};

function assignmentKey(staffId: number, employmentId: number): string {
  return `${staffId}:${employmentId}`;
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return '배정 요청을 처리하지 못했습니다.';
}

function staffLabel(staff: StaffResponse): string {
  return `${staff.display_name || staff.name} (#${staff.id})`;
}

function draftFromAssignment(assignment: CareAssignment): Draft {
  return {
    staffKey: assignmentKey(assignment.staff_id, assignment.employment_id),
    assignmentKind: assignment.assignment_kind,
    familyRelationshipText: assignment.family_relationship_text ?? '',
    startDate: assignment.start_date,
    endDate: assignment.end_date ?? '',
  };
}

export default function RecipientCareAssignmentPanel({ recipientId }: Props) {
  const [contracts, setContracts] = useState<ContractResponse[]>([]);
  const [staff, setStaff] = useState<StaffResponse[]>([]);
  const [contractId, setContractId] = useState<string>('');
  const [assignments, setAssignments] = useState<CareAssignment[]>([]);
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const generationRef = useRef(0);

  const eligibleStaff = useMemo(
    () =>
      staff.filter(
        (item) =>
          item.current_employment &&
          (item.current_positions ?? []).some(
            (position) => position.position_code === 'CARE_WORKER',
          ),
      ),
    [staff],
  );

  const activeContracts = useMemo(
    () => contracts.filter((contract) => !contract.invalidated_at_utc),
    [contracts],
  );

  const loadAssignments = useCallback(
    async (nextContractId: string, generation: number) => {
      if (!nextContractId) {
        setAssignments([]);
        return;
      }
      const response = await listCareAssignments(recipientId, nextContractId);
      if (generation !== generationRef.current) return;
      setAssignments(response.items ?? []);
    },
    [recipientId],
  );

  const load = useCallback(async () => {
    const generation = ++generationRef.current;
    setLoading(true);
    setError(null);
    setAssignments([]);
    setContracts([]);
    setStaff([]);
    try {
      const [contractResponse, staffResponse] = await Promise.all([
        listContracts(recipientId),
        fetchStaffPage({ page: 1, pageSize: 200 }),
      ]);
      if (generation !== generationRef.current) return;
      const nextContracts = contractResponse.items ?? [];
      setContracts(nextContracts);
      setStaff(staffResponse.items ?? []);
      const nextContract = nextContracts.find((item) => !item.invalidated_at_utc);
      const nextContractId = nextContract ? String(nextContract.id) : '';
      setContractId(nextContractId);
      await loadAssignments(nextContractId, generation);
    } catch (requestError) {
      if (generation === generationRef.current) setError(errorMessage(requestError));
    } finally {
      if (generation === generationRef.current) setLoading(false);
    }
  }, [loadAssignments, recipientId]);

  useEffect(() => {
    setDraft(EMPTY_DRAFT);
    setEditingId(null);
    void load();
    return () => {
      generationRef.current += 1;
    };
  }, [load]);

  const handleContractChange = (nextContractId: string) => {
    setContractId(nextContractId);
    setEditingId(null);
    setDraft(EMPTY_DRAFT);
    const generation = generationRef.current;
    setError(null);
    void loadAssignments(nextContractId, generation).catch((requestError: unknown) => {
      if (generation === generationRef.current) setError(errorMessage(requestError));
    });
  };

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!contractId || !draft.staffKey) {
      setError('계약과 요양보호사를 선택하세요.');
      return;
    }
    const [staffIdText, employmentIdText] = draft.staffKey.split(':');
    const base = {
      staff_id: Number(staffIdText),
      employment_id: Number(employmentIdText),
      assignment_kind: draft.assignmentKind,
      family_relationship_text:
        draft.assignmentKind === 'FAMILY' ? draft.familyRelationshipText.trim() || null : null,
      start_date: draft.startDate,
      end_date: draft.endDate || null,
    } satisfies CareAssignmentCreateRequest;
    if (draft.assignmentKind === 'FAMILY' && !base.family_relationship_text) {
      setError('가족요양은 관계 snapshot을 입력해야 합니다.');
      return;
    }
    const generation = generationRef.current;
    setSaving(true);
    setError(null);
    const request = editingId
      ? replaceCareAssignment(recipientId, contractId, editingId, {
          ...base,
          expected_row_version:
            assignments.find((item) => item.id === editingId)?.row_version ?? 0,
        } satisfies CareAssignmentReplaceRequest)
      : createCareAssignment(recipientId, contractId, base);
    void request
      .then(async () => {
        if (generation !== generationRef.current) return;
        setDraft(EMPTY_DRAFT);
        setEditingId(null);
        await loadAssignments(contractId, generation);
      })
      .catch((requestError: unknown) => {
        if (generation === generationRef.current) setError(errorMessage(requestError));
      })
      .finally(() => {
        if (generation === generationRef.current) setSaving(false);
      });
  };

  return (
    <section
      className="recipient-subsection recipient-care-assignment-section"
      data-testid="recipient-care-assignment-panel"
    >
      <div className="recipient-subsection-heading">
        <h3>요양보호사 배정 (W1E)</h3>
        <span>계약별 기간 배정</span>
      </div>
      {error ? (
        <div className="recipient-error" role="alert" data-testid="care-assignment-error">
          {error}
        </div>
      ) : null}
      {loading ? <div className="recipient-muted">배정 자료를 불러오는 중입니다.</div> : null}
      {!loading && !activeContracts.length ? (
        <div className="recipient-muted" data-testid="care-assignment-empty-contract">
          먼저 서비스 계약을 등록하세요.
        </div>
      ) : null}
      {!loading && activeContracts.length ? (
        <>
          <label className="recipient-field">
            계약
            <select
              data-testid="care-assignment-contract-select"
              value={contractId}
              onChange={(event) => handleContractChange(event.target.value)}
              disabled={saving}
            >
              {activeContracts.map((contract) => (
                <option key={contract.id} value={contract.id}>
                  #{contract.id} {contract.service_type_code} ({contract.start_date} ~{' '}
                  {contract.end_date ?? '계속'})
                </option>
              ))}
            </select>
          </label>
          <form className="recipient-subform" onSubmit={handleSubmit} data-testid="care-assignment-form">
            <div className="recipient-form-grid">
              <label className="recipient-field">
                요양보호사 <em>필수</em>
                <select
                  data-testid="care-assignment-staff-select"
                  value={draft.staffKey}
                  onChange={(event) => setDraft((current) => ({ ...current, staffKey: event.target.value }))}
                  required
                  disabled={saving}
                >
                  <option value="">선택하세요</option>
                  {eligibleStaff.map((item) => (
                    <option
                      key={item.id}
                      value={assignmentKey(item.id, item.current_employment!.id)}
                    >
                      {staffLabel(item)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="recipient-field">
                배정 유형 <em>필수</em>
                <select
                  data-testid="care-assignment-kind-select"
                  value={draft.assignmentKind}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      assignmentKind: event.target.value as AssignmentKind,
                    }))
                  }
                  disabled={saving}
                >
                  <option value="GENERAL">일반요양</option>
                  <option value="FAMILY">가족요양</option>
                </select>
              </label>
              <label className="recipient-field">
                시작일 <em>필수</em>
                <input
                  type="date"
                  data-testid="care-assignment-start-date-input"
                  value={draft.startDate}
                  onChange={(event) => setDraft((current) => ({ ...current, startDate: event.target.value }))}
                  required
                  disabled={saving}
                />
              </label>
              <label className="recipient-field">
                종료일
                <input
                  type="date"
                  data-testid="care-assignment-end-date-input"
                  value={draft.endDate}
                  onChange={(event) => setDraft((current) => ({ ...current, endDate: event.target.value }))}
                  disabled={saving}
                />
              </label>
              {draft.assignmentKind === 'FAMILY' ? (
                <label className="recipient-field">
                  관계 snapshot <em>필수</em>
                  <input
                    data-testid="care-assignment-family-relationship-input"
                    value={draft.familyRelationshipText}
                    onChange={(event) =>
                      setDraft((current) => ({ ...current, familyRelationshipText: event.target.value }))
                    }
                    required
                    disabled={saving}
                  />
                </label>
              ) : null}
            </div>
            <div className="recipient-history-card-actions">
              <button type="submit" className="recipient-primary-button" disabled={saving}>
                {editingId ? '배정 정정' : '배정 추가'}
              </button>
              {editingId ? (
                <button
                  type="button"
                  className="recipient-secondary-button"
                  onClick={() => {
                    setEditingId(null);
                    setDraft(EMPTY_DRAFT);
                  }}
                  disabled={saving}
                >
                  취소
                </button>
              ) : null}
            </div>
          </form>
          <div className="recipient-history-list" data-testid="care-assignment-list">
            {assignments.length ? (
              assignments.map((assignment) => (
                <div
                  className="recipient-history-card"
                  key={assignment.id}
                  data-testid={`care-assignment-row-${assignment.id}`}
                >
                  <strong>
                    {assignment.assignment_kind === 'FAMILY' ? '가족요양' : '일반요양'} · 직원 #{assignment.staff_id}
                  </strong>
                  <span>
                    {assignment.start_date} ~ {assignment.end_date ?? '계속'}
                    {assignment.family_relationship_text
                      ? ` · ${assignment.family_relationship_text}`
                      : ''}
                  </span>
                  {assignment.invalidated_at_utc ? (
                    <span className="recipient-muted">
                      정정됨{assignment.replacement_assignment_id ? ` → #${assignment.replacement_assignment_id}` : ''}
                    </span>
                  ) : (
                    <button
                      type="button"
                      className="recipient-secondary-button"
                      data-testid={`care-assignment-edit-${assignment.id}`}
                      onClick={() => {
                        setEditingId(assignment.id);
                        setDraft(draftFromAssignment(assignment));
                      }}
                      disabled={saving}
                    >
                      정정
                    </button>
                  )}
                </div>
              ))
            ) : (
              <div className="recipient-muted">등록된 배정이 없습니다.</div>
            )}
          </div>
        </>
      ) : null}
    </section>
  );
}
