import {
  useState,
  useEffect,
  type CSSProperties,
  type FormEvent,
} from 'react';
import { Link } from 'react-router';
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import {
  arrayMove,
  rectSortingStrategy,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { createTodo, setTodoStatus, isValidStatus } from '../components/dashboard/todoState';
import type { Todo } from '../components/dashboard/todoState';
import { fetchAllStaff } from '../services/staffApi';
import { listRecipientDeadlines, listRecipients, type RecipientDeadlineItem } from '../services/recipientApi';

// Display-only placeholders (not bound to live summary/API contracts).
// Ratio rows: literal 1nn/1mm. Count rows: literal 1nn + existing unit.
const staffTasks = [
  ['보수교육', '1nn/1mm'],
  ['직원상담', '1nn/1mm'],
  ['인권교육', '1nn/1mm'],
  ['연간교육', '1nn/1mm'],
  ['건강검진', '1nn/1mm'],
  ['신규교육', '1nn명'],
] as const;

const recipientTasks = [
  ['상담반영', '1nn/1mm'],
  ['반기평가', '1nn/1mm'],
  ['서류미비', '1nn건'],
  ['인정만료', '1nn건'],
  ['계약만료', '1nn건'],
] as const;


type WorkItem = {
  id: string;
  label: string;
  completed?: boolean;
};

type WorkCard = {
  id: string;
  dday: string;
  person: string;
  taskName: string;
  due: string;
  items: WorkItem[];
};

type CareWorkerLatest = {
  id: number;
  name: string;
  startDate: string;
  dplus: number;
};

const initialWorkCards: WorkCard[] = [
  {
    id: 'recipient-renewal',
    dday: 'D-13',
    person: '홍길동 수급자',
    taskName: '장기요양 계획서 갱신',
    due: '2026-08-16',
    items: [
      { id: 'renewal-check', label: '만료 전 갱신 확인' },
      { id: 'notify', label: '관련자료 제출' },
    ],
  },
  {
    id: 'staff-onboarding',
    dday: 'D-18',
    person: '이영희 요양보호사',
    taskName: '신규 직원 입사',
    due: '2026-08-21',
    items: [
      { id: 'document-check', label: '입사 서류 확인' },
      { id: 'schedule-check', label: '근무 일정 등록' },
    ],
  },
];

function SortableWorkCard({
  card,
  ddayOverride,
  onToggleItem,
}: {
  card: WorkCard;
  ddayOverride?: string;
  onToggleItem: (cardId: string, itemId: string) => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: card.id,
  });
  const style: CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.58 : 1,
    zIndex: isDragging ? 2 : undefined,
  };

  return (
    <article
      className="dashboard-work-card dashboard-work-card-oxford"
      data-testid="dashboard-work-card"
      data-card-id={card.id}
      data-note-pattern="oxford"
      ref={setNodeRef}
      style={style}
    >
      <button
        className="dashboard-card-drag-handle"
        type="button"
        aria-label={`${card.person} 임무카드 이동`}
        {...attributes}
        {...listeners}
      >
        <span aria-hidden="true">⋮⋮</span>
      </button>
      <h3>{card.person}</h3>
      <p>{card.taskName}</p>
      <ul className="dashboard-work-subtask-list">
        {card.items.map((item) => {
          const completed = item.completed === true;
          return (
            <li
              key={item.id}
              className={`dashboard-work-subtask${completed ? ' dashboard-work-subtask-completed' : ''}`}
            >
              <button
                type="button"
                className="dashboard-work-subtask-toggle"
                aria-label={completed ? `${item.label} 미완료로 표시` : `${item.label} 완료로 표시`}
                onClick={() => onToggleItem(card.id, item.id)}
              >
                <span className="dashboard-work-subtask-label">
                  <span>{item.label}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      <footer className="dashboard-work-card-footer">
        <span className="dashboard-dday" aria-label={`마감 ${ddayOverride ?? card.dday}`}>
          {ddayOverride ?? card.dday}
        </span>
        <span className="dashboard-work-card-due" aria-label={`마감일 ${card.due}`}>
          {card.due}
        </span>
      </footer>
    </article>
  );
}

function SummaryCard({
  title,
  personCount,
  linkTo,
  tasks,
}: {
  title: string;
  personCount: string;
  linkTo: string;
  tasks: readonly (readonly [string, string])[];
}) {
  return (
    <section className="dashboard-summary-card">
      <div className="dashboard-summary-heading">
        <div className="dashboard-summary-title">
          <h2>
            <Link to={linkTo} className="dashboard-summary-link">
              {title}
            </Link>
          </h2>
        </div>
        <p className="dashboard-summary-count">{personCount}</p>
      </div>
      <div className="dashboard-task-grid">
        {tasks.map(([label, count]) => (
          <div className="dashboard-task-row" key={label}>
            <span>{label}</span>
            <span className="dashboard-task-count">{count}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

const TODOS_STORAGE_KEY = 'sswcenter-dashboard-todos';

function loadTodos(): Todo[] {
  try {
    const raw = localStorage.getItem(TODOS_STORAGE_KEY);
    if (!raw) return [];
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      // malformed JSON – purge storage so stale data never returns
      try { localStorage.setItem(TODOS_STORAGE_KEY, '[]'); } catch { /* ignore */ }
      return [];
    }
    if (!Array.isArray(parsed)) {
      // non-array storage – purge and return canonical empty
      try { localStorage.setItem(TODOS_STORAGE_KEY, '[]'); } catch { /* ignore */ }
      return [];
    }

    const seen = new Set<string>();
    const canonical: Todo[] = [];

    for (const item of parsed) {
      if (typeof item?.id !== 'string' || item.id.trim().length === 0) continue;
      if (typeof item?.title !== 'string' || item.title.trim().length === 0) continue;
      if (!isValidStatus(item?.status)) continue;
      if (item.status === 'deleted') continue;

      const id = item.id.trim();
      if (seen.has(id)) continue;
      seen.add(id);

      canonical.push({
        id,
        title: item.title.trim(),
        status: item.status as 'pending' | 'completed',
      });
    }

    // Re-save canonical list so legacy / duplicate fields are purged on next read
    try {
      localStorage.setItem(TODOS_STORAGE_KEY, JSON.stringify(canonical));
    } catch {
      /* storage write failed – still return canonical data */
    }

    return canonical;
  } catch {
    // getItem/setItem throw – return empty, cannot persist
    return [];
  }
}

function saveTodos(todos: Todo[]): void {
  try {
    localStorage.setItem(TODOS_STORAGE_KEY, JSON.stringify(todos));
  } catch {
    /* storage full or unavailable – silently ignore */
  }
}

/**
 * KST 달력 날짜 기준으로 startDate(YYYY-MM-DD)부터 오늘까지의 경과 일수를 반환한다.
 * 순수 함수이며 테스트 가능하다.
 */
export function computeDaysSince(startDate: string, todayKst?: Date): number {
  const ref = todayKst ?? new Date();
  // Interpret the date string as KST (UTC+9) midnight
  const start = new Date(startDate + 'T00:00:00+09:00');
  // Truncate ref to KST calendar date midnight
  const refKst = new Date(
    ref.toLocaleDateString('en-CA', { timeZone: 'Asia/Seoul' }) + 'T00:00:00+09:00',
  );
  const diffMs = refKst.getTime() - start.getTime();
  return Math.floor(diffMs / (1000 * 60 * 60 * 24));
}

/**
 * KST 달력 날짜 기준으로 dueDate(YYYY-MM-DD)까지 남은 일수를 반환한다.
 * computeDaysSince와 동일한 KST 자정 규약을 사용한다.
 */
export function computeDaysUntil(dueDate: string, todayKst?: Date): number {
  const ref = todayKst ?? new Date();
  // Interpret the date string as KST (UTC+9) midnight
  const due = new Date(dueDate + 'T00:00:00+09:00');
  // Truncate ref to KST calendar date midnight
  const refKst = new Date(
    ref.toLocaleDateString('en-CA', { timeZone: 'Asia/Seoul' }) + 'T00:00:00+09:00',
  );
  const diffMs = due.getTime() - refKst.getTime();
  return Math.floor(diffMs / (1000 * 60 * 60 * 24));
}

function formatRecipientDeadlineDday(daysRemaining: number): string {
  return daysRemaining >= 0 ? `D-${daysRemaining}` : `D+${Math.abs(daysRemaining)}`;
}

function recipientDeadlineKindLabel(kind: RecipientDeadlineItem['kind']): string {
  switch (kind) {
    case 'CERTIFICATION_EXPIRY':
      return '인정 만료';
    case 'CONTRACT_EXPIRY':
      return '계약 만료';
    case 'PLAN_RENEWAL':
      return '계획서 갱신';
    default:
      return kind;
  }
}

export const DashboardPage = () => {
  const [workCards, setWorkCards] = useState(initialWorkCards);
  const [todos, setTodos] = useState<Todo[]>(() => loadTodos());
  const [todoText, setTodoText] = useState('');
  const [staffCount, setStaffCount] = useState<number | null>(null);
  const [recipientCount, setRecipientCount] = useState<number | null>(null);
  const [recipientDeadlines, setRecipientDeadlines] = useState<RecipientDeadlineItem[]>([]);
  const [careWorkerLatest, setCareWorkerLatest] = useState<CareWorkerLatest | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);

  useEffect(() => {
    const abortController = new AbortController();
    const { signal } = abortController;
    let active = true;

    const isStale = () => !active || signal.aborted;

    const toErrorMessage = (err: unknown): string | null => {
      if (!(err instanceof Error)) return '오류가 발생했습니다.';
      if (err.name === 'AbortError') return null;
      return err.message || '오류가 발생했습니다.';
    };

    async function loadCounts() {
      // Start employee, recipient-total, and upcoming-deadline queries concurrently
      // (no sequential waterfall). Preserve existing API bindings and semantics.
      const staffPromise = fetchAllStaff(signal);
      const recipientPromise = listRecipients({ pageSize: 1, signal });
      const deadlinePromise = listRecipientDeadlines(signal);

      const [staffSettled, recipientSettled, deadlineSettled] = await Promise.allSettled([
        staffPromise,
        recipientPromise,
        deadlinePromise,
      ]);

      if (isStale()) return;

      const errors: string[] = [];

      if (staffSettled.status === 'fulfilled') {
        const staffResult = staffSettled.value;
        setStaffCount(staffResult.total);

        // Find the most recent CARE_WORKER and compute D+ from its current employment start date
        let latestCareWorker: Omit<CareWorkerLatest, 'dplus'> | null = null;
        for (const staff of staffResult.items) {
          const positions = staff.current_positions ?? [];
          const isCareWorker = positions.some(
            (p) => p.position_code === 'CARE_WORKER',
          );
          if (isCareWorker && staff.current_employment?.start_date) {
            const start = staff.current_employment.start_date;
            if (latestCareWorker === null || start > latestCareWorker.startDate) {
              latestCareWorker = {
                id: staff.id,
                name: staff.name,
                startDate: start,
              };
            }
          }
        }
        if (latestCareWorker !== null) {
          setCareWorkerLatest({
            ...latestCareWorker,
            dplus: computeDaysSince(latestCareWorker.startDate),
          });
        }
      } else {
        const msg = toErrorMessage(staffSettled.reason);
        if (msg) errors.push(msg);
      }

      if (recipientSettled.status === 'fulfilled') {
        setRecipientCount(recipientSettled.value.total);
      } else {
        const msg = toErrorMessage(recipientSettled.reason);
        if (msg) errors.push(msg);
      }

      if (deadlineSettled.status === 'fulfilled') {
        setRecipientDeadlines(deadlineSettled.value.items);
      } else {
        const msg = toErrorMessage(deadlineSettled.reason);
        if (msg) errors.push(msg);
      }

      // Abort/unmount safety: never update state after cancel
      if (isStale()) return;

      // Partial failure: keep successful slices; render exactly one alert surface
      if (errors.length > 0) {
        setApiError([...new Set(errors)].join('; '));
      }
    }

    loadCounts();

    return () => {
      active = false;
      abortController.abort();
    };
  }, []);

  const updateTodos = (updater: (prev: Todo[]) => Todo[]) => {
    setTodos((prev) => {
      const next = updater(prev);
      saveTodos(next);
      return next;
    });
  };

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const moveWorkCard = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return;
    setWorkCards((cards) => {
      const from = cards.findIndex((card) => card.id === active.id);
      const to = cards.findIndex((card) => card.id === over.id);
      return from < 0 || to < 0 ? cards : arrayMove(cards, from, to);
    });
  };

  const toggleWorkItem = (cardId: string, itemId: string) => {
    setWorkCards((cards) =>
      cards.map((card) =>
        card.id === cardId
          ? {
              ...card,
              items: card.items.map((item) =>
                item.id === itemId
                  ? { ...item, completed: !item.completed }
                  : item,
              ),
            }
          : card,
      ),
    );
  };

  const addTodo = (event: FormEvent) => {
    event.preventDefault();
    const text = todoText.trim();
    if (!text) return;
    updateTodos((current) => [...current, createTodo({ title: text })]);
    setTodoText('');
  };

  const toggleTodo = (id: string) => {
    updateTodos((current) =>
      current.map((todo) =>
        todo.id === id
          ? setTodoStatus(todo, todo.status === 'completed' ? 'pending' : 'completed')
          : todo,
      ),
    );
  };

  const deleteTodo = (id: string) => {
    updateTodos((current) => current.filter((todo) => todo.id !== id));
  };

  return (
    <div className="dashboard-page" data-testid="page-dashboard">
      <h1 className="visually-hidden">대시보드</h1>
      {apiError && <div className="dashboard-api-error" role="alert">{apiError}</div>}
      <div className="dashboard-content-grid">
        <div className="dashboard-summary-grid">
          <SummaryCard
            title="직원"
            personCount={staffCount !== null ? `${staffCount}명` : '…'}
            linkTo="/staff"
            tasks={staffTasks}
          />
          <SummaryCard
            title="수급자"
            personCount={recipientCount !== null ? `${recipientCount}명` : '…'}
            linkTo="/recipients"
            tasks={recipientTasks}
          />
        </div>

        <div className="dashboard-top-rail">
          <section className="dashboard-rail-card dashboard-todo-card" aria-label="내할일">
            <h3>내할일</h3>
            <form className="dashboard-todo-form" onSubmit={addTodo}>
              <input
                className="dashboard-todo-input"
                aria-label="할일 입력"
                placeholder="할일 입력"
                value={todoText}
                onChange={(event) => setTodoText(event.target.value)}
              />
              <button type="submit">추가</button>
            </form>
            <ul className="dashboard-todo-list">
              {todos.map((todo) => (
                <li
                  className={`dashboard-todo-item${todo.status === 'completed' ? ' is-complete' : ''}`}
                  key={todo.id}
                >
                  <button
                    type="button"
                    className="dashboard-todo-toggle"
                    aria-label={todo.status === 'completed' ? '미완료로 표시' : '완료로 표시'}
                    onClick={() => toggleTodo(todo.id)}
                  >
                    <span className="dashboard-todo-dot" aria-hidden="true" />
                  </button>
                  <span className="dashboard-todo-copy">
                    <span>{todo.title}</span>
                  </span>
                  <button
                    type="button"
                    className="dashboard-todo-trash"
                    aria-label="할일 삭제"
                    onClick={() => deleteTodo(todo.id)}
                  >
                    <span aria-hidden="true">🗑</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>

          <section className="dashboard-rail-card dashboard-deadline-card" aria-label="다가오는 마감일">
            <h3>다가오는 마감일</h3>
            <div className="dashboard-deadline-list">
              {recipientDeadlines.length === 0 ? (
                <p className="dashboard-deadline-empty">등록된 수급자 마감일이 없습니다.</p>
              ) : (
                recipientDeadlines.map((item) => (
                  <div
                    className="dashboard-deadline-row"
                    key={`${item.kind}-${item.recipient_id}-${item.source_id}`}
                  >
                    <strong>
                      {formatRecipientDeadlineDday(computeDaysUntil(item.due_date))}
                    </strong>
                    <span className="dashboard-deadline-body">
                      <span className="dashboard-deadline-date">{item.due_date}</span>
                      <span className="dashboard-deadline-detail">
                        {`${item.recipient_name} · ${recipientDeadlineKindLabel(item.kind)}`}
                      </span>
                    </span>
                  </div>
                ))
              )}
            </div>
          </section>
        </div>

        <section className="dashboard-work-block" aria-label="임무카드">
          <DndContext sensors={sensors} onDragEnd={moveWorkCard}>
            <SortableContext items={workCards.map((card) => card.id)} strategy={rectSortingStrategy}>
              <section className="dashboard-work-area" aria-label="진행 업무">
                {workCards.map((card) => {
                  const displayCard =
                    card.id === 'staff-onboarding' && careWorkerLatest !== null
                      ? {
                          ...card,
                          dday: `D+${careWorkerLatest.dplus}`,
                          person: `${careWorkerLatest.name} 요양보호사`,
                          due: careWorkerLatest.startDate,
                        }
                      : card.id === 'recipient-renewal'
                        ? recipientDeadlines[0]
                          ? {
                              ...card,
                              dday: formatRecipientDeadlineDday(
                                computeDaysUntil(recipientDeadlines[0].due_date),
                              ),
                              person: recipientDeadlines[0].recipient_name,
                              taskName: recipientDeadlineKindLabel(recipientDeadlines[0].kind),
                              due: recipientDeadlines[0].due_date,
                            }
                          : {
                              ...card,
                              dday: '—',
                              person: '수급자 업무',
                              taskName: '등록된 마감일 없음',
                              due: '—',
                            }
                      : card;

                  return (
                    <SortableWorkCard
                      card={displayCard}
                      key={card.id}
                      onToggleItem={toggleWorkItem}
                    />
                  );
                })}
              </section>
            </SortableContext>
          </DndContext>
        </section>
      </div>
    </div>
  );
};

export default DashboardPage;
