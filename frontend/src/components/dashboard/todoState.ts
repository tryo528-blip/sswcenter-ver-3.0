/** 할일 상태: 완료와 삭제를 명확히 구분한다. */
export type TodoStatus = 'pending' | 'completed' | 'deleted';

/** 순수 todo 항목. deadline은 선택사항이다. */
export interface Todo {
  readonly id: string;
  readonly title: string;
  readonly status: TodoStatus;
  readonly deadline?: string;
}

/** createTodo 입력 계약 */
export interface CreateTodoInput {
  title: string;
  deadline?: string;
}

/**
 * 새 pending 할일을 생성한다.
 * title은 비어있지 않은 문자열이어야 한다.
 * deadline은 없어도 무방하다.
 */
export function createTodo(input: CreateTodoInput): Todo {
  if (typeof input.title !== 'string' || input.title.trim().length === 0) {
    throw new Error('title must be a non-empty string');
  }

  return {
    id: crypto.randomUUID(),
    title: input.title.trim(),
    status: 'pending',
    ...(input.deadline !== undefined ? { deadline: input.deadline } : {}),
  };
}

/**
 * 기존 todo의 상태를 변경한 새 객체를 반환한다.
 * 원본 todo는 변이하지 않는다.
 */
export function setTodoStatus(todo: Todo, status: TodoStatus): Todo {
  return { ...todo, status };
}

/**
 * todo 상태가 유효한지 검사한다.
 * (필요할 때만 사용하는 보조 함수)
 */
export function isValidStatus(status: string): status is TodoStatus {
  return status === 'pending' || status === 'completed' || status === 'deleted';
}

/**
 * todo가 주어진 상태인지 검사한다.
 * 완료와 삭제를 구분할 때 명시적으로 사용한다.
 */
export function isTodoStatus(todo: Todo, status: TodoStatus): boolean {
  return todo.status === status;
}
