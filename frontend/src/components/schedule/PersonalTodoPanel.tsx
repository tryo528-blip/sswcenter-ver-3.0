import { useEffect, useState, type FormEvent, type KeyboardEvent } from 'react';
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import {
  W2ConflictError,
  createPersonalTodo,
  deletePersonalTodo,
  listPersonalTodos,
  reorderPersonalTodos,
  updatePersonalTodo,
  type PersonalTodo,
  type PersonalTodoList,
} from '../../services/w2Api';

const EMPTY_TODOS: PersonalTodoList = { items: [], listRevision: 1 };

function SortableTodo({
  todo,
  busy,
  onToggle,
  onRename,
  onDelete,
}: {
  todo: PersonalTodo;
  busy: boolean;
  onToggle: (todo: PersonalTodo) => void;
  onRename: (todo: PersonalTodo, title: string) => void;
  onDelete: (todo: PersonalTodo) => void;
}) {
  const [titleDraft, setTitleDraft] = useState(todo.title);
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: todo.id,
    disabled: busy,
  });

  useEffect(() => setTitleDraft(todo.title), [todo.id, todo.title]);

  const saveTitle = () => {
    const title = titleDraft.trim();
    if (!title) {
      setTitleDraft(todo.title);
      return;
    }
    if (title !== todo.title) onRename(todo, title);
  };

  const handleTitleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter') event.currentTarget.blur();
    if (event.key === 'Escape') {
      setTitleDraft(todo.title);
      event.currentTarget.blur();
    }
  };

  return (
    <li
      className={`schedule-todo-item${todo.completed ? ' is-complete' : ''}`}
      ref={setNodeRef}
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: isDragging ? 0.45 : undefined,
      }}
    >
      <button
        type="button"
        className="schedule-todo-drag"
        aria-label={`${todo.title} 순서 변경`}
        disabled={busy}
        {...attributes}
        {...listeners}
      >
        <span aria-hidden="true">⋮⋮</span>
      </button>
      <button
        type="button"
        className="schedule-todo-toggle"
        aria-label={todo.completed ? '할 일 미완료로 전환' : '할 일 완료로 전환'}
        aria-pressed={todo.completed}
        disabled={busy}
        onClick={() => onToggle(todo)}
      >
        <span aria-hidden="true" />
      </button>
      <input
        aria-label={`${todo.title} 제목`}
        className="schedule-todo-title"
        disabled={busy}
        value={titleDraft}
        onBlur={saveTitle}
        onChange={(event) => setTitleDraft(event.target.value)}
        onKeyDown={handleTitleKeyDown}
      />
      <button
        type="button"
        className="schedule-todo-delete"
        aria-label={`${todo.title} 삭제`}
        disabled={busy}
        onClick={() => onDelete(todo)}
      >
        삭제
      </button>
    </li>
  );
}

export function PersonalTodoPanel() {
  const [todoList, setTodoList] = useState<PersonalTodoList>(EMPTY_TODOS);
  const [title, setTitle] = useState('');
  const [busyIds, setBusyIds] = useState<ReadonlySet<number | 'new'>>(new Set());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [latestConflict, setLatestConflict] = useState<PersonalTodoList | null>(null);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    listPersonalTodos(controller.signal)
      .then((result) => {
        setTodoList(result);
        setError(null);
      })
      .catch((requestError: unknown) => {
        if (requestError instanceof Error && requestError.name === 'AbortError') return;
        setError(requestError instanceof Error ? requestError.message : '개인 할 일을 불러오지 못했습니다.');
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, []);

  const setBusy = (id: number | 'new', busy: boolean) => {
    setBusyIds((current) => {
      const next = new Set(current);
      if (busy) next.add(id);
      else next.delete(id);
      return next;
    });
  };

  const handleConflict = (requestError: unknown) => {
    if (requestError instanceof W2ConflictError) {
      setLatestConflict(requestError.latestTodoList ?? null);
      setError('다른 창에서 먼저 변경되었습니다. 현재 목록과 서버 최신본을 자동으로 합치지 않았습니다.');
      return;
    }
    setError(requestError instanceof Error ? requestError.message : '개인 할 일을 저장하지 못했습니다.');
  };

  const addTodo = async (event: FormEvent) => {
    event.preventDefault();
    const normalizedTitle = title.trim();
    if (!normalizedTitle) return;
    setBusy('new', true);
    setError(null);
    try {
      setTodoList(await createPersonalTodo(normalizedTitle, todoList.listRevision));
      setTitle('');
    } catch (requestError) {
      handleConflict(requestError);
    } finally {
      setBusy('new', false);
    }
  };

  const toggleTodo = async (todo: PersonalTodo) => {
    setBusy(todo.id, true);
    setError(null);
    try {
      setTodoList(await updatePersonalTodo(
        todo,
        todoList.listRevision,
        { completed: !todo.completed },
      ));
    } catch (requestError) {
      handleConflict(requestError);
    } finally {
      setBusy(todo.id, false);
    }
  };

  const renameTodo = async (todo: PersonalTodo, nextTitle: string) => {
    setBusy(todo.id, true);
    setError(null);
    try {
      setTodoList(await updatePersonalTodo(todo, todoList.listRevision, { title: nextTitle }));
    } catch (requestError) {
      handleConflict(requestError);
    } finally {
      setBusy(todo.id, false);
    }
  };

  const removeTodo = async (todo: PersonalTodo) => {
    setBusy(todo.id, true);
    setError(null);
    try {
      setTodoList(await deletePersonalTodo(todo, todoList.listRevision));
    } catch (requestError) {
      handleConflict(requestError);
    } finally {
      setBusy(todo.id, false);
    }
  };

  const reorderTodos = async ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return;
    const oldIndex = todoList.items.findIndex((item) => item.id === active.id);
    const newIndex = todoList.items.findIndex((item) => item.id === over.id);
    if (oldIndex < 0 || newIndex < 0) return;

    const optimistic = arrayMove([...todoList.items], oldIndex, newIndex);
    const previous = todoList;
    setTodoList({ ...todoList, items: optimistic });
    setError(null);
    try {
      setTodoList(await reorderPersonalTodos(
        optimistic.map((item) => item.id),
        todoList.listRevision,
      ));
    } catch (requestError) {
      setTodoList(previous);
      handleConflict(requestError);
    }
  };

  return (
    <aside className="schedule-todo-panel" aria-label="개인 할 일">
      <div className="schedule-panel-heading">
        <div><span>본인 전용</span><h2>개인 할 일</h2></div>
      </div>
      <form className="schedule-todo-form" onSubmit={addTodo}>
        <input
          aria-label="새 할 일 제목"
          placeholder="할 일 입력"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
        />
        <button
          type="submit"
          disabled={loading || busyIds.has('new') || title.trim() === ''}
        >
          추가
        </button>
      </form>
      {error && <p className="schedule-panel-error" role="alert">{error}</p>}
      {latestConflict && (
        <div className="schedule-conflict-box" data-testid="todo-latest-conflict">
          <strong>서버 최신본 {latestConflict.items.length}건</strong>
          <button
            type="button"
            onClick={() => {
              setTodoList(latestConflict);
              setLatestConflict(null);
              setError(null);
            }}
          >
            최신본으로 다시 열기
          </button>
        </div>
      )}
      {loading ? (
        <p className="schedule-panel-empty">불러오는 중…</p>
      ) : todoList.items.length === 0 ? (
        <p className="schedule-panel-empty">등록된 개인 할 일이 없습니다.</p>
      ) : (
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={reorderTodos}>
          <SortableContext
            items={todoList.items.map((todo) => todo.id)}
            strategy={verticalListSortingStrategy}
          >
            <ul className="schedule-todo-list">
              {todoList.items.map((todo) => (
                <SortableTodo
                  busy={busyIds.has(todo.id)}
                  key={todo.id}
                  onDelete={(item) => void removeTodo(item)}
                  onRename={(item, nextTitle) => void renameTodo(item, nextTitle)}
                  onToggle={(item) => void toggleTodo(item)}
                  todo={todo}
                />
              ))}
            </ul>
          </SortableContext>
        </DndContext>
      )}
    </aside>
  );
}
