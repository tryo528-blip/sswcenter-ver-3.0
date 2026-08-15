import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { ApiError } from '../../services/api';
import { fetchAllRecipients, type RecipientListItem } from '../../services/recipientApi';
import {
  createProfessionalAssignment,
  fetchAllProfessionalAssignmentStaffOptions,
  listProfessionalAssignments,
  replaceProfessionalAssignment,
  type ProfessionalAssignment,
  type ProfessionalAssignmentInput,
  type ProfessionalAssignmentStaffOption,
} from '../../services/professionalAssignmentApi';
import { fetchSessionCapabilities } from '../../services/staffApi';

type ProfessionalPosition = 'SOCIAL_WORKER' | 'NURSE';

type StaffChoice = {
  staff: ProfessionalAssignmentStaffOption;
  employmentId: number;
  positionCode: ProfessionalPosition;
};

function monthStart(month: string): string {
  return `${month}-01`;
}

function monthEnd(month: string): string {
  const [year, rawMonth] = month.split('-').map(Number);
  const lastDay = new Date(Date.UTC(year, rawMonth, 0)).getUTCDate();
  return `${month}-${String(lastDay).padStart(2, '0')}`;
}

function currentMonth(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return '전문직 담당 요청을 처리하지 못했습니다.';
}

function nextDate(value: string): string {
  const date = new Date(`${value}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + 1);
  return date.toISOString().slice(0, 10);
}

function previousDate(value: string): string {
  const date = new Date(`${value}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() - 1);
  return date.toISOString().slice(0, 10);
}

function periodsCoverWindow(
  periods: Array<{ start_date: string; end_date: string | null }>,
  windowStart: string,
  windowEnd: string,
): boolean {
  let cursor = windowStart;
  const relevant = periods
    .filter(
      (period) =>
        period.start_date <= windowEnd
        && (period.end_date === null || period.end_date >= windowStart),
    )
    .sort((left, right) => left.start_date.localeCompare(right.start_date));
  for (const period of relevant) {
    if (period.start_date > cursor) return false;
    const effectiveEnd = period.end_date ?? '9999-12-31';
    if (effectiveEnd >= windowEnd) return true;
    if (effectiveEnd >= cursor) cursor = nextDate(effectiveEnd);
  }
  return false;
}

function assignmentKey(staffId: number, employmentId: number): string {
  return `${staffId}:${employmentId}`;
}

function staffLabel(
  staff: ProfessionalAssignmentStaffOption,
  positionCode: ProfessionalPosition,
): string {
  const positionLabel = positionCode === 'NURSE' ? '간호사' : '사회복지사';
  return `${staff.display_name || staff.name} · ${positionLabel} (#${staff.id})`;
}

function recipientLabel(recipient: RecipientListItem): string {
  return `${recipient.name?.trim() || '미입력'} (#${recipient.id})`;
}

function staffHistoryCanCover(
  staff: ProfessionalAssignmentStaffOption,
  employmentId: number,
  windowStart: string,
  windowEnd: string,
): ProfessionalPosition | null {
  const employment = staff.employments.find((item) => item.id === employmentId);
  if (
    !employment
    || !periodsCoverWindow([employment], windowStart, windowEnd)
  ) {
    return null;
  }
  const positions = staff.positions.filter(
    (item) =>
      item.employment_id === employmentId
      && (item.position_code === 'SOCIAL_WORKER' || item.position_code === 'NURSE'),
  );
  if (!periodsCoverWindow(positions, windowStart, windowEnd)) return null;
  const position = positions
    .filter(
      (item) =>
        item.start_date <= windowStart
        && (item.end_date === null || item.end_date >= windowStart),
    )
    .sort((left, right) => right.start_date.localeCompare(left.start_date))[0];
  return position?.position_code === 'SOCIAL_WORKER' || position?.position_code === 'NURSE'
    ? position.position_code
    : null;
}

function uncoveredAssignmentIntervals(
  assignments: ProfessionalAssignment[],
  windowStart: string,
  windowEnd: string,
): Array<{ start_date: string; end_date: string }> {
  let cursor = windowStart;
  const intervals: Array<{ start_date: string; end_date: string }> = [];
  const active = assignments
    .filter((assignment) => assignment.invalidated_at_utc === null)
    .filter(
      (assignment) => assignment.start_date <= windowEnd && assignment.end_date >= windowStart,
    )
    .sort((left, right) => left.start_date.localeCompare(right.start_date));
  for (const assignment of active) {
    if (assignment.start_date > cursor) {
      intervals.push({ start_date: cursor, end_date: previousDate(assignment.start_date) });
    }
    if (assignment.end_date >= cursor) {
      cursor = nextDate(assignment.end_date);
      if (cursor > windowEnd) break;
    }
  }
  if (cursor <= windowEnd) intervals.push({ start_date: cursor, end_date: windowEnd });
  return intervals;
}

export default function ProfessionalAssignmentWorkspace() {
  const [month, setMonth] = useState(currentMonth);
  const [recipients, setRecipients] = useState<RecipientListItem[]>([]);
  const [staff, setStaff] = useState<ProfessionalAssignmentStaffOption[]>([]);
  const [recipientId, setRecipientId] = useState('');
  const [assignments, setAssignments] = useState<ProfessionalAssignment[]>([]);
  const [staffKey, setStaffKey] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [editingId, setEditingId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [canManage, setCanManage] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const generationRef = useRef(0);
  const mutationRef = useRef(0);
  const contextRef = useRef({ recipientId, month });
  contextRef.current = { recipientId, month };

  const eligibleStaff = useMemo(() => {
    const windowStart = startDate || monthStart(month);
    const windowEnd = endDate || monthEnd(month);
    const choices = new Map<string, StaffChoice>();
    for (const item of staff) {
      for (const employment of item.employments) {
        const positionCode = staffHistoryCanCover(
          item,
          employment.id,
          windowStart,
          windowEnd,
        );
        if (!positionCode) continue;
        choices.set(assignmentKey(item.id, employment.id), {
          staff: item,
          employmentId: employment.id,
          positionCode,
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
        choices.set(key, {
          staff: editingStaff,
          employmentId: editingAssignment.employment_id,
          positionCode: 'SOCIAL_WORKER',
        });
      }
    }
    return [...choices.values()].sort((left, right) =>
      staffLabel(left.staff, left.positionCode).localeCompare(
        staffLabel(right.staff, right.positionCode),
        'ko',
      ),
    );
  }, [assignments, editingId, endDate, month, staff, startDate]);

  useEffect(() => {
    if (staffKey && !eligibleStaff.some(({ staff: item, employmentId }) =>
      assignmentKey(item.id, employmentId) === staffKey)) {
      setStaffKey('');
    }
  }, [eligibleStaff, staffKey]);

  const loadAssignments = useCallback(
    async (nextRecipientId: string, nextMonth: string, generation: number) => {
      if (!nextRecipientId) {
        if (generation === generationRef.current) setAssignments([]);
        return;
      }
      try {
        const response = await listProfessionalAssignments(
          nextRecipientId,
          monthStart(nextMonth),
        );
        if (generation !== generationRef.current) return;
        setAssignments(response.items ?? []);
      } catch (requestError) {
        if (generation === generationRef.current) setError(errorMessage(requestError));
      } finally {
        if (generation === generationRef.current) setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    void fetchAllRecipients(controller.signal)
      .then((response) => {
        if (active) setRecipients(response.items);
      })
      .catch((requestError: unknown) => {
        if (active) setError(errorMessage(requestError));
      });

    void fetchSessionCapabilities(controller.signal)
      .then(async (capabilities) => {
        if (!active) return;
        const manage = capabilities['recipient.manage'] === true;
        setCanManage(manage);
        if (!manage) {
          setStaff([]);
          return;
        }
        try {
          const response = await fetchAllProfessionalAssignmentStaffOptions(controller.signal);
          if (active) setStaff(response.items);
        } catch (requestError: unknown) {
          if (active && !(requestError instanceof ApiError && requestError.status === 403)) {
            setError(errorMessage(requestError));
          }
        }
      })
      .catch(() => {
        if (active) setCanManage(false);
      });

    return () => {
      active = false;
      controller.abort();
      generationRef.current += 1;
    };
  }, []);

  useEffect(() => {
    const generation = ++generationRef.current;
    setStartDate(monthStart(month));
    setEndDate(monthEnd(month));
    setEditingId(null);
    setStaffKey('');
    setAssignments([]);
    setSaving(false);
    setLoading(Boolean(recipientId));
    setError(null);
    void loadAssignments(recipientId, month, generation);
  }, [loadAssignments, month, recipientId]);

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!recipientId || !staffKey) {
      setError('수급자와 전문직 담당자를 선택하세요.');
      return;
    }
    const [staffIdText, employmentIdText] = staffKey.split(':');
    const payload: ProfessionalAssignmentInput = {
      staff_id: Number(staffIdText),
      employment_id: Number(employmentIdText),
      start_date: startDate,
      end_date: endDate,
    };
    const current = editingId ? assignments.find((item) => item.id === editingId) : null;
    const mutationToken = ++mutationRef.current;
    setSaving(true);
    setError(null);
    const request = current
      ? replaceProfessionalAssignment(recipientId, monthStart(month), current.id, {
          ...payload,
          expected_row_version: current.row_version,
        })
      : createProfessionalAssignment(recipientId, monthStart(month), payload);
    void request
      .then(async () => {
        const currentContext = contextRef.current;
        if (
          mutationToken !== mutationRef.current
          ||
          String(currentContext.recipientId) !== String(recipientId)
          || currentContext.month !== month
        ) return;
        setEditingId(null);
        setStaffKey('');
        await loadAssignments(recipientId, month, generationRef.current);
        if (mutationToken !== mutationRef.current) return;
      })
      .catch((requestError: unknown) => {
        if (mutationToken !== mutationRef.current) return;
        const currentContext = contextRef.current;
        if (
          String(currentContext.recipientId) === String(recipientId)
          && currentContext.month === month
        ) {
          setError(errorMessage(requestError));
        }
      })
      .finally(() => {
        const currentContext = contextRef.current;
        if (
          mutationToken === mutationRef.current
          &&
          String(currentContext.recipientId) === String(recipientId)
          && currentContext.month === month
        ) {
          setSaving(false);
        }
      });
  };

  return (
    <section className="professional-assignment-workspace" data-testid="professional-assignment-workspace">
      <div className="professional-assignment-toolbar">
        <label>
          수급자
          <select
            aria-label="전문직 담당 수급자"
            data-testid="professional-assignment-recipient-select"
            value={recipientId}
            onChange={(event) => setRecipientId(event.target.value)}
          >
            <option value="">선택하세요</option>
            {recipients.map((recipient) => (
              <option key={recipient.id} value={recipient.id}>
                {recipientLabel(recipient)}
              </option>
            ))}
          </select>
        </label>
        <label>
          서비스월
          <input
            type="month"
            aria-label="전문직 담당 서비스월"
            data-testid="professional-assignment-month-input"
            value={month}
            onChange={(event) => setMonth(event.target.value || currentMonth())}
          />
        </label>
      </div>
      {error ? (
        <p role="alert" className="professional-assignment-error">
          {error}
        </p>
      ) : null}
      {recipientId ? (
        <>
          {canManage ? <form onSubmit={handleSubmit} className="professional-assignment-form">
            <label>
              담당자
              <select
                data-testid="professional-assignment-staff-select"
                value={staffKey}
                onChange={(event) => setStaffKey(event.target.value)}
                required
                disabled={saving}
              >
                <option value="">선택하세요</option>
                {eligibleStaff.map(({ staff: item, employmentId, positionCode }) => (
                  <option
                    key={assignmentKey(item.id, employmentId)}
                    value={assignmentKey(item.id, employmentId)}
                  >
                    {staffLabel(item, positionCode)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              시작일
              <input
                type="date"
                value={startDate}
                onChange={(event) => setStartDate(event.target.value)}
                required
                disabled={saving}
              />
            </label>
            <label>
              종료일
              <input
                type="date"
                value={endDate}
                onChange={(event) => setEndDate(event.target.value)}
                required
                disabled={saving}
              />
            </label>
            <button type="submit" disabled={saving}>
              {editingId ? '담당 정정' : '담당 추가'}
            </button>
            {editingId ? (
              <button
                type="button"
                onClick={() => {
                  setEditingId(null);
                  setStaffKey('');
                  setStartDate(monthStart(month));
                  setEndDate(monthEnd(month));
                }}
                disabled={saving}
              >
                취소
              </button>
            ) : null}
          </form> : null}
          <div className="professional-assignment-history" data-testid="professional-assignment-history">
            {loading ? <p>담당 이력을 불러오는 중입니다.</p> : null}
            {!loading && !assignments.length ? <p>담당 없음</p> : null}
            {!loading && assignments.length
              ? uncoveredAssignmentIntervals(assignments, monthStart(month), monthEnd(month)).map((interval) => (
                  <p key={`${interval.start_date}-${interval.end_date}`} data-testid="professional-assignment-gap">
                    담당 없음 · {interval.start_date} ~ {interval.end_date}
                  </p>
                ))
              : null}
            {assignments.map((assignment) => (
              <article key={assignment.id} data-testid={`professional-assignment-row-${assignment.id}`}>
                <strong>
                  {staff.find((item) => item.id === assignment.staff_id)?.display_name
                    || staff.find((item) => item.id === assignment.staff_id)?.name
                    || '직원'}
                  {' '}#{assignment.staff_id} · {assignment.start_date} ~ {assignment.end_date}
                </strong>
                {assignment.invalidated_at_utc ? (
                  <span>정정됨{assignment.replacement_assignment_id ? ` → #${assignment.replacement_assignment_id}` : ''}</span>
                ) : (
                  canManage ? <button
                    type="button"
                    onClick={() => {
                      setEditingId(assignment.id);
                      setStaffKey(assignmentKey(assignment.staff_id, assignment.employment_id));
                      setStartDate(assignment.start_date);
                      setEndDate(assignment.end_date);
                    }}
                  >
                    정정
                  </button> : null
                )}
              </article>
            ))}
          </div>
        </>
      ) : (
        <p>수급자를 선택하면 월중 전문직 담당과 변경 이력이 표시됩니다.</p>
      )}
    </section>
  );
}
