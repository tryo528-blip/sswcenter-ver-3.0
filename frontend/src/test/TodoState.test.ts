import { describe, it, expect } from 'vitest';
import {
  createTodo,
  setTodoStatus,
  isValidStatus,
  isTodoStatus,
} from '../components/dashboard/todoState';
import type { Todo } from '../components/dashboard/todoState';

describe('TodoState', () => {
  // 1. 날짜 없는 할일 생성 가능
  it('creates a todo without deadline', () => {
    const todo = createTodo({ title: '산책하기' });
    expect(todo.title).toBe('산책하기');
    expect(todo.deadline).toBeUndefined();
    expect(todo.status).toBe('pending');
    expect(typeof todo.id).toBe('string');
    expect(todo.id.length).toBeGreaterThan(0);
  });

  // 2. 날짜가 있는 할일 보존
  it('creates a todo with deadline and preserves it', () => {
    const todo = createTodo({ title: '보고서 제출', deadline: '2025-12-25' });
    expect(todo.title).toBe('보고서 제출');
    expect(todo.deadline).toBe('2025-12-25');
    expect(todo.status).toBe('pending');
  });

  // 3. 기본 상태 pending
  it('defaults status to pending on creation', () => {
    const todo = createTodo({ title: 'A' });
    expect(todo.status).toBe('pending');
  });

  // 4. pending -> completed
  it('transitions from pending to completed', () => {
    const todo = createTodo({ title: '완료할 일' });
    const completed = setTodoStatus(todo, 'completed');
    expect(completed.status).toBe('completed');
    expect(todo.status).toBe('pending'); // 원본 불변
  });

  // 5. pending -> deleted
  it('transitions from pending to deleted', () => {
    const todo = createTodo({ title: '삭제할 일' });
    const deleted = setTodoStatus(todo, 'deleted');
    expect(deleted.status).toBe('deleted');
    expect(todo.status).toBe('pending');
  });

  // 6. completed와 deleted가 서로 다른 상태
  it('distinguishes completed from deleted', () => {
    const todo = createTodo({ title: '구분 테스트' });
    const comp = setTodoStatus(todo, 'completed');
    const del = setTodoStatus(todo, 'deleted');

    expect(comp.status).not.toBe(del.status);
    expect(isTodoStatus(comp, 'completed')).toBe(true);
    expect(isTodoStatus(comp, 'deleted')).toBe(false);
    expect(isTodoStatus(del, 'deleted')).toBe(true);
    expect(isTodoStatus(del, 'completed')).toBe(false);
  });

  // 7. 상태 변경이 원본 객체를 변이하지 않음
  it('does not mutate the original todo on status change', () => {
    const original = createTodo({ title: '불변 테스트', deadline: '2025-06-01' });
    const frozen = Object.freeze(original);

    // Object.freeze 된 객체로도 안전하게 동작해야 함
    const updated = setTodoStatus(frozen as Todo, 'completed');
    expect(updated.status).toBe('completed');
    expect(frozen.status).toBe('pending');
    expect(updated).not.toBe(frozen);
    expect(updated.id).toBe(frozen.id);
    expect(updated.title).toBe(frozen.title);
    expect((updated as Todo).deadline).toBe(frozen.deadline);
  });

  // 8. 입력 검증
  it('throws on empty or whitespace-only title', () => {
    expect(() => createTodo({ title: '' })).toThrow('title must be a non-empty string');
    expect(() => createTodo({ title: '   ' })).toThrow('title must be a non-empty string');
  });

  it('isValidStatus accepts only valid statuses', () => {
    expect(isValidStatus('pending')).toBe(true);
    expect(isValidStatus('completed')).toBe(true);
    expect(isValidStatus('deleted')).toBe(true);
    expect(isValidStatus('archived')).toBe(false);
    expect(isValidStatus('')).toBe(false);
    expect(isValidStatus('PENDING')).toBe(false);
  });

  // 9. completed → pending reverse toggle
  it('transitions from completed back to pending', () => {
    const todo = createTodo({ title: '되돌릴 일' });
    const completed = setTodoStatus(todo, 'completed');
    expect(completed.status).toBe('completed');
    const backToPending = setTodoStatus(completed, 'pending');
    expect(backToPending.status).toBe('pending');
    // original and intermediate untouched
    expect(todo.status).toBe('pending');
    expect(completed.status).toBe('completed');
  });

  // 10. deleted items filtered separately from completed
  it('keeps deleted status distinct and filterable', () => {
    const todos = [
      createTodo({ title: 'A' }),
      createTodo({ title: 'B' }),
      createTodo({ title: 'C' }),
    ];
    const modified = [
      setTodoStatus(todos[0], 'completed'),
      setTodoStatus(todos[1], 'deleted'),
      todos[2], // stays pending
    ];

    const activeOnly = modified.filter((t) => t.status !== 'deleted');
    expect(activeOnly).toHaveLength(2);
    expect(activeOnly.find((t) => t.status === 'completed')).toBeTruthy();
    expect(activeOnly.find((t) => t.status === 'pending')).toBeTruthy();
    expect(activeOnly.find((t) => t.status === 'deleted')).toBeUndefined();
  });
});
