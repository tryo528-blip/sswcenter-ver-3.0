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
import {
  fetchAllStaff,
  fetchStaffDetail,
  fetchStaffServiceQualifications,
  type StaffDetailResponse,
  type StaffServiceQualificationResponse,
  type StaffResponse,
} from '../../services/staffApi';
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

function nextDate(value: string): string {
  const [year, month, day] = value.split('-').map(Number);
  return new Date(Date.UTC(year, month - 1, day + 1)).toISOString().slice(0, 10);
}

function periodsCoverWindow(
  periods: Array<{ start_date: string; end_date: string | null }>,
  windowStart: string,
  windowEnd: string,
): boolean {
  let cursor = windowStart;
  const ordered = [...periods].sort((left, right) => left.start_date.localeCompare(right.start_date));
  for (const period of ordered) {
    const effectiveEnd = period.end_date ?? '9999-12-31';
    if (period.start_date > cursor || effectiveEnd < cursor) continue;
    if (effectiveEnd >= windowEnd) return true;
    cursor = nextDate(effectiveEnd);
  }
  return false;
}

function staffHistoryCanCover(
  staff: StaffResponse,
  details: StaffDetailResponse | undefined,
  employmentId: number,
  windowStart: string,
  windowEnd: string,
): boolean {
  const employment = (details?.employments ?? []).find((item) => item.id === employmentId)
    ?? (staff.current_employment?.id === employmentId ? staff.current_employment : null);
  if (
    !employment ||
    !periodsCoverWindow([employment], windowStart, windowEnd)
  ) {
    return false;
  }
  const positions = details?.positions?.filter((item) => item.employment_id === employmentId)
    ?? (staff.current_employment?.id === employmentId ? staff.current_positions ?? [] : []);
  return periodsCoverWindow(
    positions
      .filter((position) => position.position_code === 'CARE_WORKER')
      .map((position) => ({ start_date: position.start_date, end_date: position.end_date })),
    windowStart,
    windowEnd,
  );
}

const STAFF_DETAIL_CONCURRENCY = 6;
type StaffContext = {
  detail: StaffDetailResponse;
  qualifications: StaffServiceQualificationResponse[];
};

async function mapStaffContexts(
  staffItems: StaffResponse[],
  signal?: AbortSignal,
): Promise<ReadonlyMap<number, StaffContext>> {
  const entries: Array<readonly [number, StaffContext] | null> = new Array(staffItems.length).fill(null);
  let nextIndex = 0;

  async function worker(): Promise<void> {
    while (true) {
      if (signal?.aborted) return;
      const index = nextIndex++;
      if (index >= staffItems.length) return;
      const item = staffItems[index];
      try {
        const detail = await fetchStaffDetail(item.id, signal);
        if (signal?.aborted) return;
        let qualifications: StaffServiceQualificationResponse[] = [];
        try {
          qualifications = (await fetchStaffServiceQualifications(item.id, signal)).items ?? [];
        } catch {
          if (signal?.aborted) return;
          // GENERAL choices fail closed without qualification evidence; FAMILY
          // choices can still use employment/position history.
        }
        entries[index] = [item.id, {
          detail,
          qualifications,
        }];
      } catch {
        if (signal?.aborted) return;
        entries[index] = null;
      }
    }
  }

  await Promise.all(
    Array.from(
      { length: Math.min(STAFF_DETAIL_CONCURRENCY, staffItems.length) },
      () => worker(),
    ),
  );
  return new Map(
    entries.filter(
      (entry): entry is readonly [number, StaffContext] => entry !== null,
    ),
  );
}

export default function RecipientCareAssignmentPanel({ recipientId }: Props) {
  const [contracts, setContracts] = useState<ContractResponse[]>([]);
  const [staff, setStaff] = useState<StaffResponse[]>([]);
  const [staffDetails, setStaffDetails] = useState<Record<number, StaffDetailResponse>>({});
  const [staffQualifications, setStaffQualifications] = useState<
    Record<number, StaffServiceQualificationResponse[]>
  >({});
  const [contractId, setContractId] = useState<string>('');
  const [assignments, setAssignments] = useState<CareAssignment[]>([]);
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const generationRef = useRef(0);
  const staffLoadAbortRef = useRef<AbortController | null>(null);

  const activeContracts = useMemo(
    () => contracts.filter((contract) => !contract.invalidated_at_utc),
    [contracts],
  );

  const selectedContract = useMemo(
    () => activeContracts.find((contract) => String(contract.id) === contractId),
    [activeContracts, contractId],
  );

  const eligibleStaff = useMemo(() => {
    const windowStart = draft.startDate || selectedContract?.start_date || '';
    const windowEnd = draft.endDate || selectedContract?.end_date || '9999-12-31';
    if (!windowStart) return [];
    const serviceTypeCode = selectedContract?.service_type_code;
    const choices = new Map<string, { staff: StaffResponse; employmentId: number }>();
    for (const item of staff) {
      const details = staffDetails[item.id];
      const employments = details?.employments
        ?? (item.current_employment ? [item.current_employment] : []);
      for (const employment of employments) {
        if (!staffHistoryCanCover(item, details, employment.id, windowStart, windowEnd)) continue;
        if (
          draft.assignmentKind === 'GENERAL' &&
          (!serviceTypeCode || !periodsCoverWindow(
            (staffQualifications[item.id] ?? []).filter(
              (qualification) =>
                qualification.employment_id === employment.id &&
                qualification.service_type_code === serviceTypeCode &&
                qualification.invalidated_at_utc === null,
            ),
            windowStart,
            windowEnd,
          ))
        ) {
          continue;
        }
        choices.set(assignmentKey(item.id, employment.id), {
          staff: item,
          employmentId: employment.id,
        });
      }
    }

    const editingAssignment = editingId
      ? assignments.find((assignment) => assignment.id === editingId)
      : null;
    if (editingAssignment) {
      const editingStaff = staff.find((item) => item.id === editingAssignment.staff_id);
      const key = assignmentKey(editingAssignment.staff_id, editingAssignment.employment_id);
      if (editingStaff && !choices.has(key)) {
        choices.set(key, { staff: editingStaff, employmentId: editingAssignment.employment_id });
      }
    }
    return [...choices.values()].sort((left, right) =>
      staffLabel(left.staff).localeCompare(staffLabel(right.staff), 'ko'),
    );
  }, [
    assignments,
    draft.assignmentKind,
    draft.endDate,
    draft.startDate,
    editingId,
    selectedContract,
    staff,
    staffDetails,
    staffQualifications,
  ]);

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
    staffLoadAbortRef.current?.abort();
    const staffLoadController = new AbortController();
    staffLoadAbortRef.current = staffLoadController;
    const generation = ++generationRef.current;
    setLoading(true);
    setError(null);
    setAssignments([]);
    setContracts([]);
    setStaff([]);
    setStaffDetails({});
    setStaffQualifications({});
    try {
      const contractResponse = await listContracts(recipientId, staffLoadController.signal);
      if (generation !== generationRef.current) return;
      const nextContracts = contractResponse.items ?? [];
      setContracts(nextContracts);
      const nextContract = nextContracts.find((item) => !item.invalidated_at_utc);
      const nextContractId = nextContract ? String(nextContract.id) : '';
      setContractId(nextContractId);
      await loadAssignments(nextContractId, generation);

      // Staff access is independent from recipient assignment-history access.
      // A 403 here must not hide the already-authorized contract history.
      try {
      const staffResponse = await fetchAllStaff(staffLoadController.signal);
        if (generation !== generationRef.current) return;
        setStaff(staffResponse.items);
        const contextEntries = await mapStaffContexts(
          staffResponse.items,
          staffLoadController.signal,
        );
        if (generation !== generationRef.current) return;
        setStaffDetails(
          Object.fromEntries(
            [...contextEntries.entries()].map(([staffId, context]) => [staffId, context.detail]),
          ),
        );
        setStaffQualifications(
          Object.fromEntries(
            [...contextEntries.entries()].map(([staffId, context]) => [staffId, context.qualifications]),
          ),
        );
      } catch (staffError) {
        if (generation === generationRef.current && !(staffError instanceof ApiError && staffError.status === 403)) {
          setError(errorMessage(staffError));
        }
      }
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
      staffLoadAbortRef.current?.abort();
      staffLoadAbortRef.current = null;
    };
  }, [load]);

  const handleContractChange = (nextContractId: string) => {
    const generation = ++generationRef.current;
    setContractId(nextContractId);
    setEditingId(null);
    setDraft(EMPTY_DRAFT);
    setAssignments([]);
    setLoading(true);
    setError(null);
    void loadAssignments(nextContractId, generation).catch((requestError: unknown) => {
      if (generation === generationRef.current) setError(errorMessage(requestError));
    }).finally(() => {
      if (generation === generationRef.current) setLoading(false);
    });
  };

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!contractId || !draft.staffKey) {
      setError('계약과 요양보호사를 선택하세요.');
      return;
    }
    if (selectedContract?.end_date && !draft.endDate) {
      setError('종료된 계약에는 배정 종료일을 입력해야 합니다.');
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
                  {eligibleStaff.map(({ staff: item, employmentId }) => (
                    <option
                      key={assignmentKey(item.id, employmentId)}
                      value={assignmentKey(item.id, employmentId)}
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
