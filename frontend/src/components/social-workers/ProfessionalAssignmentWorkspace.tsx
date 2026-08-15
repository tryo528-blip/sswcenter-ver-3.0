import { useCallback, useEffect, useMemo, useState } from 'react';
import type { FormEvent } from 'react';
import { ApiError } from '../../services/api';
import { listRecipients, type RecipientListItem } from '../../services/recipientApi';
import {
  createProfessionalAssignment,
  listProfessionalAssignments,
  replaceProfessionalAssignment,
  type ProfessionalAssignment,
  type ProfessionalAssignmentInput,
} from '../../services/professionalAssignmentApi';
import { fetchStaffPage, type StaffResponse } from '../../services/staffApi';

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

function staffLabel(staff: StaffResponse): string {
  const position = (staff.current_positions ?? []).find(
    (item) => item.position_code === 'SOCIAL_WORKER' || item.position_code === 'NURSE',
  );
  const positionLabel = position?.position_code === 'NURSE' ? '간호사' : '사회복지사';
  return `${staff.display_name || staff.name} · ${positionLabel} (#${staff.id})`;
}

function recipientLabel(recipient: RecipientListItem): string {
  return `${recipient.name?.trim() || '미입력'} (#${recipient.id})`;
}

export default function ProfessionalAssignmentWorkspace() {
  const [month, setMonth] = useState(currentMonth);
  const [recipients, setRecipients] = useState<RecipientListItem[]>([]);
  const [staff, setStaff] = useState<StaffResponse[]>([]);
  const [recipientId, setRecipientId] = useState('');
  const [assignments, setAssignments] = useState<ProfessionalAssignment[]>([]);
  const [staffKey, setStaffKey] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [editingId, setEditingId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const eligibleStaff = useMemo(
    () =>
      staff.filter(
        (item) =>
          item.current_employment &&
          (item.current_positions ?? []).some(
            (position) =>
              position.position_code === 'SOCIAL_WORKER' || position.position_code === 'NURSE',
          ),
      ),
    [staff],
  );

  const loadAssignments = useCallback(async () => {
    if (!recipientId) {
      setAssignments([]);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await listProfessionalAssignments(recipientId, monthStart(month));
      setAssignments(response.items ?? []);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setLoading(false);
    }
  }, [month, recipientId]);

  useEffect(() => {
    let active = true;
    void Promise.all([
      listRecipients({ page: 1, pageSize: 200 }),
      fetchStaffPage({ page: 1, pageSize: 200 }),
    ])
      .then(([recipientResponse, staffResponse]) => {
        if (!active) return;
        setRecipients(recipientResponse.items ?? []);
        setStaff(staffResponse.items ?? []);
      })
      .catch((requestError: unknown) => {
        if (active) setError(errorMessage(requestError));
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    setStartDate(monthStart(month));
    setEndDate(monthEnd(month));
    setEditingId(null);
    void loadAssignments();
  }, [loadAssignments, month]);

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
        setEditingId(null);
        setStaffKey('');
        await loadAssignments();
      })
      .catch((requestError: unknown) => setError(errorMessage(requestError)))
      .finally(() => setSaving(false));
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
            onChange={(event) => {
              setRecipientId(event.target.value);
              setEditingId(null);
              setAssignments([]);
            }}
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
          <form onSubmit={handleSubmit} className="professional-assignment-form">
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
                {eligibleStaff.map((item) => (
                  <option
                    key={item.id}
                    value={`${item.id}:${item.current_employment!.id}`}
                  >
                    {staffLabel(item)}
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
          </form>
          <div className="professional-assignment-history" data-testid="professional-assignment-history">
            {loading ? <p>담당 이력을 불러오는 중입니다.</p> : null}
            {!loading && !assignments.length ? <p>담당 없음</p> : null}
            {assignments.map((assignment) => (
              <article key={assignment.id} data-testid={`professional-assignment-row-${assignment.id}`}>
                <strong>
                  직원 #{assignment.staff_id} · {assignment.start_date} ~ {assignment.end_date}
                </strong>
                {assignment.invalidated_at_utc ? (
                  <span>정정됨{assignment.replacement_assignment_id ? ` → #${assignment.replacement_assignment_id}` : ''}</span>
                ) : (
                  <button
                    type="button"
                    onClick={() => {
                      setEditingId(assignment.id);
                      setStaffKey(`${assignment.staff_id}:${assignment.employment_id}`);
                      setStartDate(assignment.start_date);
                      setEndDate(assignment.end_date);
                    }}
                  >
                    정정
                  </button>
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
