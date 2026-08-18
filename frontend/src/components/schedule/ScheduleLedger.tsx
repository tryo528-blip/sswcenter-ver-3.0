import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from 'react';
import type { ScheduleKind } from './schedulePopups';
import {
  W2ConflictError,
  createSchedule,
  deleteSchedule,
  finalizeScheduleMonth,
  listSchedules,
  projectScheduleMonthSnapshot,
  replaceSchedule,
  type ScheduleItem,
  type ScheduleMonthSnapshot,
  type ScheduleSnapshotFilter,
} from '../../services/w2Api';

const EMPTY_SCHEDULE_ITEMS: readonly ScheduleItem[] = [];

type Draft = {
  editingId: number | null;
  expectedRowVersion: number | null;
  recipientId: string;
  staffId1: string;
  employmentId1: string;
  staffId2: string;
  employmentId2: string;
  serviceTypeId: string;
  startsAtLocal: string;
  endsAtLocal: string;
};

type ScheduleQueryVisit = {
  readonly id: number;
  readonly key: string;
  readonly month: string;
  readonly scheduleMonth: string;
  readonly filter: ScheduleSnapshotFilter;
};

type ScheduleMutationOwner = {
  readonly id: number;
  readonly queryVisitId: number;
  readonly key: string;
  readonly month: string;
  readonly scheduleMonth: string;
  readonly filter: ScheduleSnapshotFilter;
};

type OwnedScheduleConflict = {
  readonly snapshot: ScheduleMonthSnapshot;
  readonly queryVisitId: number;
  readonly mutationId: number;
};

function scheduleMonthDate(month: string): string {
  return `${month}-01`;
}

function emptyDraft(month: string): Draft {
  return {
    editingId: null,
    expectedRowVersion: null,
    recipientId: '',
    staffId1: '',
    employmentId1: '',
    staffId2: '',
    employmentId2: '',
    serviceTypeId: '',
    startsAtLocal: `${month}-01T09:00`,
    endsAtLocal: `${month}-01T10:00`,
  };
}

function monthCells(month: string): Array<number | null> {
  const [year, monthNumber] = month.split('-').map(Number);
  const firstDay = new Date(year, monthNumber - 1, 1).getDay();
  const lastDay = new Date(year, monthNumber, 0).getDate();
  const cells: Array<number | null> = Array.from({ length: firstDay }, () => null);
  for (let day = 1; day <= lastDay; day += 1) cells.push(day);
  while (cells.length % 7 !== 0) cells.push(null);
  return cells;
}

function dateFor(month: string, day: number): string {
  return `${month}-${String(day).padStart(2, '0')}`;
}

function positiveInteger(value: string): number | null {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

export function kstLocalInputToUtc(value: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value);
  if (!match) throw new Error('날짜와 시간을 정확히 입력해주세요.');
  const [, year, month, day, hour, minute] = match.map(Number);
  return new Date(Date.UTC(year, month - 1, day, hour - 9, minute)).toISOString();
}

export function utcToKstLocalInput(value: string): string {
  const utc = new Date(value);
  if (Number.isNaN(utc.getTime())) return '';
  return new Date(utc.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 16);
}

function kstDate(value: string): string {
  return utcToKstLocalInput(value).slice(0, 10);
}

function kstTime(value: string): string {
  return utcToKstLocalInput(value).slice(11, 16);
}

function itemTitle(item: ScheduleItem): string {
  return `서비스 ${item.serviceTypeId}`;
}

function itemViewLabel(item: ScheduleItem, kind: ScheduleKind): string {
  return kind === 'recipient'
    ? `직원 ${item.assignedStaff.map((assigned) => assigned.staffId).join('·')}`
    : `수급자 ${item.recipientId}`;
}

function requestErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '일정을 처리하지 못했습니다.';
}

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === 'AbortError';
}

function scheduleQueryFilter(
  kind: ScheduleKind,
  filterId: number | undefined,
): ScheduleSnapshotFilter {
  if (filterId === undefined) return {};
  return kind === 'recipient' ? { recipientId: filterId } : { staffId: filterId };
}

function scheduleQueryVisit(
  id: number,
  key: string,
  kind: ScheduleKind,
  month: string,
  filterId: number | undefined,
): ScheduleQueryVisit {
  return {
    id,
    key,
    month,
    scheduleMonth: scheduleMonthDate(month),
    filter: scheduleQueryFilter(kind, filterId),
  };
}

export function ScheduleLedger({ kind, month }: { kind: ScheduleKind; month: string }) {
  const [snapshot, setSnapshot] = useState<ScheduleMonthSnapshot>({
    scheduleMonth: scheduleMonthDate(month),
    rowVersion: 1,
    finalized: false,
    finalizedAtUtc: null,
    items: [],
  });
  const [draft, setDraft] = useState<Draft>(() => emptyDraft(month));
  const [filterDraft, setFilterDraft] = useState('');
  const [appliedFilterId, setAppliedFilterId] = useState<number | undefined>();
  const cells = useMemo(() => monthCells(month), [month]);
  const filterLabel = kind === 'recipient' ? '수급자 ID 조회' : '직원 ID 조회';
  const queryKey = useMemo(
    () => JSON.stringify([scheduleMonthDate(month), kind, appliedFilterId]),
    [appliedFilterId, kind, month],
  );
  const [queryVisit, setQueryVisit] = useState<ScheduleQueryVisit>(
    () => scheduleQueryVisit(1, queryKey, kind, month, appliedFilterId),
  );
  const [latestConflict, setLatestConflict] = useState<OwnedScheduleConflict | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadedQueryVisitId, setLoadedQueryVisitId] = useState<number | null>(null);
  const nextQueryVisitIdRef = useRef(2);
  const activeQueryVisitRef = useRef(queryVisit);
  const nextMutationIdRef = useRef(1);
  const activeMutationRef = useRef<ScheduleMutationOwner | null>(null);
  const mutationFallbackAbortRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);
  const previousKindRef = useRef(kind);
  const queryAligned = queryVisit.key === queryKey;
  const snapshotProven = queryAligned && loadedQueryVisitId === queryVisit.id;
  const mutationsLocked = saving || loading || !snapshotProven;
  const visibleItems = !loading && snapshotProven ? snapshot.items : EMPTY_SCHEDULE_ITEMS;
  const visibleConflict = latestConflict?.queryVisitId === queryVisit.id && queryAligned
    ? latestConflict
    : null;

  const itemsByDate = useMemo(() => {
    const grouped = new Map<string, ScheduleItem[]>();
    for (const item of visibleItems) {
      const date = kstDate(item.startsAtUtc);
      const current = grouped.get(date) ?? [];
      current.push(item);
      grouped.set(date, current);
    }
    return grouped;
  }, [visibleItems]);

  useLayoutEffect(() => {
    if (previousKindRef.current === kind) return;
    previousKindRef.current = kind;
    setFilterDraft('');
    setAppliedFilterId(undefined);
  }, [kind]);

  useLayoutEffect(() => {
    if (activeQueryVisitRef.current.key === queryKey) return;
    mutationFallbackAbortRef.current?.abort();
    mutationFallbackAbortRef.current = null;
    const nextVisit = scheduleQueryVisit(
      nextQueryVisitIdRef.current,
      queryKey,
      kind,
      month,
      appliedFilterId,
    );
    nextQueryVisitIdRef.current += 1;
    activeQueryVisitRef.current = nextVisit;
    setQueryVisit(nextVisit);
  }, [appliedFilterId, kind, month, queryKey]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      mutationFallbackAbortRef.current?.abort();
      mutationFallbackAbortRef.current = null;
    };
  }, []);

  useEffect(() => {
    setDraft(emptyDraft(month));
    setLatestConflict(null);
  }, [kind, month]);

  useEffect(() => {
    if (activeQueryVisitRef.current.id !== queryVisit.id) return undefined;
    const controller = new AbortController();
    const requestedVisit = queryVisit;
    setLoadedQueryVisitId(null);
    setLoading(true);
    setError(null);
    setLatestConflict(null);
    listSchedules({
      month: requestedVisit.scheduleMonth,
      ...requestedVisit.filter,
      signal: controller.signal,
    })
      .then((nextSnapshot) => {
        if (
          !mountedRef.current
          || controller.signal.aborted
          || activeQueryVisitRef.current.id !== requestedVisit.id
        ) return;
        setSnapshot(projectScheduleMonthSnapshot(nextSnapshot, requestedVisit.filter));
        setLoadedQueryVisitId(requestedVisit.id);
      })
      .catch((requestError: unknown) => {
        if (
          !mountedRef.current
          || controller.signal.aborted
          || activeQueryVisitRef.current.id !== requestedVisit.id
        ) return;
        if (isAbortError(requestError)) return;
        setError(requestErrorMessage(requestError));
      })
      .finally(() => {
        if (
          mountedRef.current
          && activeQueryVisitRef.current.id === requestedVisit.id
          && !controller.signal.aborted
        ) {
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [queryVisit]);

  const canSurfaceOwnedMutation = (owner: ScheduleMutationOwner): boolean => (
    Boolean(mountedRef.current)
    && activeMutationRef.current?.id === owner.id
    && activeQueryVisitRef.current.key === owner.key
  );

  const invalidateActiveVisitForOwnedQuery = (owner: ScheduleMutationOwner) => {
    if (!canSurfaceOwnedMutation(owner)) return;
    const nextVisit: ScheduleQueryVisit = {
      id: nextQueryVisitIdRef.current,
      key: owner.key,
      month: owner.month,
      scheduleMonth: owner.scheduleMonth,
      filter: owner.filter,
    };
    nextQueryVisitIdRef.current += 1;
    activeQueryVisitRef.current = nextVisit;
    setQueryVisit(nextVisit);
    setLoadedQueryVisitId(null);
    setLoading(true);
    setError(null);
    setLatestConflict(null);
  };

  const applyOwnedMutationSuccess = (
    owner: ScheduleMutationOwner,
    nextSnapshot: ScheduleMonthSnapshot,
    resetDraft = false,
  ) => {
    if (!canSurfaceOwnedMutation(owner)) return;
    const active = activeQueryVisitRef.current;
    if (active.id === owner.queryVisitId) {
      setSnapshot(projectScheduleMonthSnapshot(nextSnapshot, owner.filter));
      setLoadedQueryVisitId(owner.queryVisitId);
      setLatestConflict(null);
      if (resetDraft) setDraft(emptyDraft(owner.month));
      return;
    }
    if (resetDraft) setDraft(emptyDraft(owner.month));
    invalidateActiveVisitForOwnedQuery(owner);
  };

  const showConflict = async (
    requestError: unknown,
    owner: ScheduleMutationOwner,
  ) => {
    if (!canSurfaceOwnedMutation(owner)) return;
    if (!(requestError instanceof W2ConflictError)) {
      setError(requestErrorMessage(requestError));
      return;
    }
    const targetVisitId = activeQueryVisitRef.current.id;
    let latest = requestError.latestScheduleSnapshot;
    if (!latest) {
      mutationFallbackAbortRef.current?.abort();
      const fallbackController = new AbortController();
      mutationFallbackAbortRef.current = fallbackController;
      try {
        latest = await listSchedules({
          month: owner.scheduleMonth,
          ...owner.filter,
          signal: fallbackController.signal,
        });
      } catch (fallbackError) {
        if (isAbortError(fallbackError)) return;
        // Keep the original conflict message if the fallback read also fails.
      }
      if (mutationFallbackAbortRef.current === fallbackController) {
        mutationFallbackAbortRef.current = null;
      }
    }
    if (!canSurfaceOwnedMutation(owner)) return;
    if (activeQueryVisitRef.current.id !== targetVisitId) return;
    setLatestConflict(latest ? {
      snapshot: projectScheduleMonthSnapshot(latest, owner.filter),
      queryVisitId: targetVisitId,
      mutationId: owner.id,
    } : null);
    setError('다른 요청이 먼저 저장되었습니다. 입력값은 보존했고 서버 최신본을 자동으로 합치지 않았습니다.');
  };

  const beginOwnedMutation = (): ScheduleMutationOwner | null => {
    if (activeMutationRef.current || loading || !snapshotProven) return null;
    const owner: ScheduleMutationOwner = {
      id: nextMutationIdRef.current,
      queryVisitId: queryVisit.id,
      key: queryVisit.key,
      month: queryVisit.month,
      scheduleMonth: queryVisit.scheduleMonth,
      filter: queryVisit.filter,
    };
    nextMutationIdRef.current += 1;
    activeMutationRef.current = owner;
    setSaving(true);
    setError(null);
    return owner;
  };

  const finishOwnedMutation = (owner: ScheduleMutationOwner) => {
    if (activeMutationRef.current?.id !== owner.id) return;
    activeMutationRef.current = null;
    if (mountedRef.current) setSaving(false);
  };

  const startEditing = (item: ScheduleItem) => {
    const [first, second] = item.assignedStaff;
    setDraft({
      editingId: item.id,
      expectedRowVersion: item.rowVersion,
      recipientId: String(item.recipientId),
      staffId1: first ? String(first.staffId) : '',
      employmentId1: first ? String(first.employmentId) : '',
      staffId2: second ? String(second.staffId) : '',
      employmentId2: second ? String(second.employmentId) : '',
      serviceTypeId: String(item.serviceTypeId),
      startsAtLocal: utcToKstLocalInput(item.startsAtUtc),
      endsAtLocal: utcToKstLocalInput(item.endsAtUtc),
    });
    setError(null);
  };

  const saveDraft = async (event: FormEvent) => {
    event.preventDefault();
    if (activeMutationRef.current || loading || !snapshotProven) return;
    const recipientId = positiveInteger(draft.recipientId);
    const staffId1 = positiveInteger(draft.staffId1);
    const employmentId1 = positiveInteger(draft.employmentId1);
    const serviceTypeId = positiveInteger(draft.serviceTypeId);
    if (
      recipientId === null
      || staffId1 === null
      || employmentId1 === null
      || serviceTypeId === null
    ) {
      setError('수급자, 첫 번째 직원·재직, 서비스 유형 ID는 1 이상의 정수여야 합니다.');
      return;
    }
    const hasSecondStaff = draft.staffId2.trim() !== '' || draft.employmentId2.trim() !== '';
    const staffId2 = hasSecondStaff ? positiveInteger(draft.staffId2) : null;
    const employmentId2 = hasSecondStaff ? positiveInteger(draft.employmentId2) : null;
    if (hasSecondStaff && (staffId2 === null || employmentId2 === null)) {
      setError('두 번째 담당자를 입력할 때는 직원 ID와 재직 ID를 모두 입력해주세요.');
      return;
    }
    if (staffId2 !== null && staffId2 === staffId1) {
      setError('방문목욕의 두 담당 직원은 서로 달라야 합니다.');
      return;
    }

    let startsAtUtc: string;
    let endsAtUtc: string;
    try {
      startsAtUtc = kstLocalInputToUtc(draft.startsAtLocal);
      endsAtUtc = kstLocalInputToUtc(draft.endsAtLocal);
    } catch (conversionError) {
      setError(requestErrorMessage(conversionError));
      return;
    }
    if (!draft.startsAtLocal.startsWith(`${month}-`) || startsAtUtc >= endsAtUtc) {
      setError('선택한 월 안에서 시작 시각보다 종료 시각을 늦게 입력해주세요.');
      return;
    }

    const owned = beginOwnedMutation();
    if (!owned) return;
    try {
      const commonInput = {
        recipientId,
        assignedStaff: [
          { staffId: staffId1, employmentId: employmentId1 },
          ...(staffId2 !== null && employmentId2 !== null
            ? [{ staffId: staffId2, employmentId: employmentId2 }]
            : []),
        ],
        serviceTypeId,
        startsAtUtc,
        endsAtUtc,
        expectedMonthRowVersion: snapshot.rowVersion,
      };
      const nextSnapshot = draft.editingId !== null && draft.expectedRowVersion !== null
        ? await replaceSchedule(draft.editingId, {
          ...commonInput,
          expectedRowVersion: draft.expectedRowVersion,
        })
        : await createSchedule({
          ...commonInput,
          scheduleMonth: owned.scheduleMonth,
        });
      applyOwnedMutationSuccess(owned, nextSnapshot, true);
    } catch (requestError) {
      await showConflict(requestError, owned);
    } finally {
      finishOwnedMutation(owned);
    }
  };

  const removeDraftSchedule = async () => {
    if (draft.editingId === null || draft.expectedRowVersion === null) return;
    const owned = beginOwnedMutation();
    if (!owned) return;
    try {
      const nextSnapshot = await deleteSchedule(draft.editingId, {
        expectedMonthRowVersion: snapshot.rowVersion,
        expectedRowVersion: draft.expectedRowVersion,
      });
      applyOwnedMutationSuccess(owned, nextSnapshot, true);
    } catch (requestError) {
      await showConflict(requestError, owned);
    } finally {
      finishOwnedMutation(owned);
    }
  };

  const finalizeMonth = async () => {
    const owned = beginOwnedMutation();
    if (!owned) return;
    try {
      const nextSnapshot = await finalizeScheduleMonth(
        owned.scheduleMonth,
        snapshot.rowVersion,
      );
      applyOwnedMutationSuccess(owned, nextSnapshot);
    } catch (requestError) {
      await showConflict(requestError, owned);
    } finally {
      finishOwnedMutation(owned);
    }
  };

  const acceptLatest = () => {
    if (
      !latestConflict
      || loading
      || saving
      || !snapshotProven
      || latestConflict.queryVisitId !== queryVisit.id
      || activeQueryVisitRef.current.id !== queryVisit.id
    ) return;
    const accepted = projectScheduleMonthSnapshot(
      latestConflict.snapshot,
      queryVisit.filter,
    );
    setSnapshot(accepted);
    setLoadedQueryVisitId(queryVisit.id);
    setDraft((current) => {
      if (current.editingId === null) return current;
      const currentItem = accepted.items.find((item) => item.id === current.editingId);
      return currentItem
        ? { ...current, expectedRowVersion: currentItem.rowVersion }
        : { ...current, editingId: null, expectedRowVersion: null };
    });
    setLatestConflict(null);
    setError(null);
  };

  const applyFilter = (event: FormEvent) => {
    event.preventDefault();
    if (activeMutationRef.current || saving) return;
    if (filterDraft.trim() === '') {
      setAppliedFilterId(undefined);
      return;
    }
    const nextFilter = positiveInteger(filterDraft);
    if (nextFilter === null) {
      setError(`${filterLabel} 값은 1 이상의 정수여야 합니다.`);
      return;
    }
    setAppliedFilterId(nextFilter);
  };

  return (
    <section
      className="schedule-ledger"
      aria-label={`${kind === 'recipient' ? '수급자' : '직원'} 일정 원장`}
    >
      <div className="schedule-ledger-main">
        <div className="schedule-ledger-summary">
          <span>공용 schedules 원장 · version {snapshot.rowVersion}</span>
          <button
            type="button"
            disabled={mutationsLocked || snapshot.finalized}
            onClick={() => void finalizeMonth()}
          >
            {snapshot.finalized ? '확정됨' : '월 확정'}
          </button>
        </div>
        <form className="schedule-ledger-filter" onSubmit={applyFilter}>
          <label>
            {filterLabel}
            <input
              inputMode="numeric"
              value={filterDraft}
              disabled={saving}
              onChange={(event) => setFilterDraft(event.target.value)}
            />
          </label>
          <button type="submit" disabled={saving}>조회</button>
        </form>
        {error && <p className="schedule-panel-error" role="alert">{error}</p>}
        {visibleConflict && (
          <section className="schedule-latest-snapshot" data-testid="schedule-latest-snapshot">
            <div>
              <strong>서버 최신본 · version {visibleConflict.snapshot.rowVersion}</strong>
              <span>현재 입력에는 자동 반영하지 않았습니다.</span>
            </div>
            <ul>
              {visibleConflict.snapshot.items.map((item) => (
                <li key={item.id}>
                  {kstDate(item.startsAtUtc)} · {itemTitle(item)} · {itemViewLabel(item, kind)}
                </li>
              ))}
            </ul>
            <button type="button" onClick={acceptLatest}>최신본 기준으로 계속 편집</button>
          </section>
        )}
        <section className="schedule-calendar" aria-label={`${month} 일정`}>
          <div className="schedule-weekdays" aria-hidden="true">
            {['일', '월', '화', '수', '목', '금', '토'].map((day) => (
              <span key={day}>{day}</span>
            ))}
          </div>
          <div className="schedule-calendar-grid">
            {cells.map((day, index) => {
              const serviceDate = day === null ? '' : dateFor(month, day);
              const dateItems = day === null ? [] : (itemsByDate.get(serviceDate) ?? []);
              return (
                <div className={day === null ? 'is-empty' : ''} key={`${month}-${index}`}>
                  {day !== null && <span className="schedule-calendar-day">{day}</span>}
                  {dateItems.map((item) => (
                    <button
                      type="button"
                      className="schedule-calendar-entry"
                      key={item.id}
                      onClick={() => startEditing(item)}
                    >
                      <strong>{itemTitle(item)}</strong>
                      <small>
                        {kstTime(item.startsAtUtc)} · {itemViewLabel(item, kind)}
                      </small>
                    </button>
                  ))}
                </div>
              );
            })}
          </div>
        </section>
        {loading && <p className="schedule-panel-empty">일정을 불러오는 중…</p>}
        {!loading && snapshotProven && visibleItems.length === 0 && (
          <p className="schedule-panel-empty">등록된 일정이 없습니다.</p>
        )}
      </div>

      <form className="schedule-draft-panel" aria-label="일정 임시입력" onSubmit={saveDraft}>
        <div className="schedule-panel-heading">
          <div>
            <span>저장 전 임시입력</span>
            <h2>{draft.editingId === null ? '새 일정' : '일정 수정'}</h2>
          </div>
          {draft.editingId !== null && (
            <button type="button" onClick={() => setDraft(emptyDraft(month))}>새로 입력</button>
          )}
        </div>
        <div className="schedule-draft-pair">
          <label>
            수급자 ID
            <input
              inputMode="numeric"
              value={draft.recipientId}
              onChange={(event) => setDraft({ ...draft, recipientId: event.target.value })}
            />
          </label>
          <label>
            담당 직원 1 ID
            <input
              inputMode="numeric"
              value={draft.staffId1}
              onChange={(event) => setDraft({ ...draft, staffId1: event.target.value })}
            />
          </label>
        </div>
        <div className="schedule-draft-pair">
          <label>
            담당 직원 1 재직 ID
            <input
              inputMode="numeric"
              value={draft.employmentId1}
              onChange={(event) => setDraft({ ...draft, employmentId1: event.target.value })}
            />
          </label>
          <label>
            담당 직원 2 ID (방문목욕)
            <input
              inputMode="numeric"
              value={draft.staffId2}
              onChange={(event) => setDraft({ ...draft, staffId2: event.target.value })}
            />
          </label>
        </div>
        <label>
          담당 직원 2 재직 ID (방문목욕)
          <input
            inputMode="numeric"
            value={draft.employmentId2}
            onChange={(event) => setDraft({ ...draft, employmentId2: event.target.value })}
          />
        </label>
        <label>
          서비스 유형 ID
          <input
            inputMode="numeric"
            value={draft.serviceTypeId}
            onChange={(event) => setDraft({ ...draft, serviceTypeId: event.target.value })}
          />
        </label>
        <label>
          시작
          <input
            type="datetime-local"
            value={draft.startsAtLocal}
            onChange={(event) => setDraft({ ...draft, startsAtLocal: event.target.value })}
          />
        </label>
        <label>
          종료
          <input
            type="datetime-local"
            value={draft.endsAtLocal}
            onChange={(event) => setDraft({ ...draft, endsAtLocal: event.target.value })}
          />
        </label>
        <p className="schedule-draft-note">
          409 발생 시 이 입력은 유지되며 서버 최신본과 자동 병합되지 않습니다.
        </p>
        <div className="schedule-draft-actions">
          {draft.editingId !== null && (
            <button
              className="schedule-draft-delete"
              type="button"
              disabled={mutationsLocked || snapshot.finalized}
              onClick={() => void removeDraftSchedule()}
            >
              일정 삭제
            </button>
          )}
          <button
            className="schedule-draft-submit"
            type="submit"
            disabled={mutationsLocked || snapshot.finalized}
          >
            {saving ? '저장 중…' : '임시저장'}
          </button>
        </div>
      </form>
    </section>
  );
}
