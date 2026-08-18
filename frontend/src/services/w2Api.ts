import { apiRequest, ApiError } from './api';

type JsonRecord = Record<string, unknown>;

export const W2_ENDPOINTS = {
  officialWorkCards: '/api/v1/official-work-cards',
  officialWorkCardEligibleAssignees: '/api/v1/official-work-cards/eligible-assignees',
  personalTodos: '/api/v1/personal-todos',
  personalTodoReorder: '/api/v1/personal-todos/reorder',
  schedules: '/api/v1/schedules',
  scheduleMonthFinalize: (scheduleMonth: string) =>
    `/api/v1/schedule-months/${encodeURIComponent(scheduleMonth)}/finalize`,
  servicePlanNotices: (recipientId: number | string) =>
    `/api/v1/recipients/${encodeURIComponent(recipientId)}/service-plan-notices`,
} as const;

export const OFFICIAL_WORK_CARD_KINDS = [
  'RECOGNITION_EXPIRY',
  'CONTRACT_EXPIRY',
  'PLAN_NOTICE',
  'STAFF_REPLACEMENT_CONSULTATION',
  'NEW_STAFF_WORK',
] as const;

export type OfficialWorkCardKind = (typeof OFFICIAL_WORK_CARD_KINDS)[number];

export interface OfficialWorkCard {
  readonly id: number;
  readonly rowVersion: number;
  readonly kind: OfficialWorkCardKind;
  readonly assigneeStaffId: number;
  readonly assigneeStaffName: string;
  readonly title: string;
  readonly targetName: string;
  readonly detail: string;
  readonly dueDate: string;
  readonly dDay: number;
}

export interface OfficialWorkCardEligibleAssignee {
  readonly staffId: number;
  readonly staffName: string;
}

export interface OfficialWorkCardEligibleAssigneeList {
  readonly asOfDate: string;
  readonly items: readonly OfficialWorkCardEligibleAssignee[];
}

export interface OfficialWorkCardGroup {
  readonly staffId: number;
  readonly staffName: string;
  readonly cards: readonly OfficialWorkCard[];
}

export interface OfficialWorkCardCollection {
  readonly asOfDate: string;
  readonly groups: readonly OfficialWorkCardGroup[];
}

export interface PersonalTodo {
  readonly id: number;
  readonly title: string;
  readonly completed: boolean;
  readonly order: number;
  readonly rowVersion: number;
}

export interface PersonalTodoList {
  readonly items: readonly PersonalTodo[];
  readonly listRevision: number;
}

export interface ScheduleItem {
  readonly id: number;
  readonly scheduleMonth: string;
  readonly recipientId: number;
  readonly assignedStaff: readonly ScheduleAssignedStaff[];
  readonly serviceTypeId: number;
  readonly startsAtUtc: string;
  readonly endsAtUtc: string;
  readonly rowVersion: number;
}

export interface ScheduleAssignedStaff {
  readonly staffId: number;
  readonly employmentId: number;
}

export interface ScheduleAssignedStaffInput {
  readonly staffId: number;
  readonly employmentId: number;
}

export interface ScheduleMonthSnapshot {
  readonly scheduleMonth: string;
  readonly finalized: boolean;
  readonly finalizedAtUtc: string | null;
  readonly rowVersion: number;
  readonly items: readonly ScheduleItem[];
}

export interface ScheduleSnapshotFilter {
  readonly recipientId?: number;
  readonly staffId?: number;
}

export interface ScheduleListParams {
  readonly month: string;
  readonly recipientId?: number;
  readonly staffId?: number;
  readonly signal?: AbortSignal;
}

export interface ScheduleCreateInput {
  readonly scheduleMonth: string;
  readonly recipientId: number;
  readonly assignedStaff: readonly ScheduleAssignedStaffInput[];
  readonly serviceTypeId: number;
  readonly startsAtUtc: string;
  readonly endsAtUtc: string;
  readonly expectedMonthRowVersion: number;
}

export interface ScheduleReplaceInput {
  readonly recipientId: number;
  readonly assignedStaff: readonly ScheduleAssignedStaffInput[];
  readonly serviceTypeId: number;
  readonly startsAtUtc: string;
  readonly endsAtUtc: string;
  readonly expectedMonthRowVersion: number;
  readonly expectedRowVersion: number;
}

export interface ScheduleDeleteInput {
  readonly expectedMonthRowVersion: number;
  readonly expectedRowVersion: number;
}

export interface ServicePlanNotice {
  readonly id: number;
  readonly recipientId: number;
  readonly recipientContractId: number;
  readonly notificationDate: string;
  readonly appliedStartDate: string;
  readonly appliedEndDate: string;
  readonly invalidatedAtUtc: string | null;
  readonly replacementServicePlanNoticeId: number | null;
  readonly rowVersion: number;
}

export interface ServicePlanNoticeHistory {
  readonly items: readonly ServicePlanNotice[];
}

export interface ServicePlanNoticeInput {
  readonly recipientContractId: number;
  readonly notificationDate: string;
  readonly appliedStartDate: string;
  readonly appliedEndDate?: string | null;
}

export class W2ConflictError extends Error {
  readonly latestScheduleSnapshot?: ScheduleMonthSnapshot;
  readonly latestTodoList?: PersonalTodoList;
  readonly latestServicePlanHistory?: ServicePlanNoticeHistory;
  readonly latestOfficialWorkCards?: OfficialWorkCardCollection;

  constructor(
    message: string,
    options: {
      latestScheduleSnapshot?: ScheduleMonthSnapshot;
      latestTodoList?: PersonalTodoList;
      latestServicePlanHistory?: ServicePlanNoticeHistory;
      latestOfficialWorkCards?: OfficialWorkCardCollection;
    } = {},
  ) {
    super(message);
    this.name = 'W2ConflictError';
    this.latestScheduleSnapshot = options.latestScheduleSnapshot;
    this.latestTodoList = options.latestTodoList;
    this.latestServicePlanHistory = options.latestServicePlanHistory;
    this.latestOfficialWorkCards = options.latestOfficialWorkCards;
  }
}

function asRecord(value: unknown): JsonRecord | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as JsonRecord)
    : null;
}

function requireRecord(value: unknown, label: string): JsonRecord {
  const record = asRecord(value);
  if (!record) throw new Error(`Invalid ${label} payload`);
  return record;
}

function requireString(record: JsonRecord, key: string, label: string): string {
  const value = record[key];
  if (typeof value !== 'string') throw new Error(`Invalid ${label}.${key}`);
  return value;
}

function requireNumber(record: JsonRecord, key: string, label: string): number {
  const value = record[key];
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new Error(`Invalid ${label}.${key}`);
  }
  return value;
}

function requireBoolean(record: JsonRecord, key: string, label: string): boolean {
  const value = record[key];
  if (typeof value !== 'boolean') throw new Error(`Invalid ${label}.${key}`);
  return value;
}

function requireArray(record: JsonRecord, key: string, label: string): readonly unknown[] {
  const value = record[key];
  if (!Array.isArray(value)) throw new Error(`Invalid ${label}.${key}`);
  return value;
}

function displayName(value: string): string {
  const normalized = value.trim();
  return normalized || '미입력';
}

function normalizeOfficialWorkCardKind(value: unknown): OfficialWorkCardKind {
  if (
    typeof value === 'string'
    && (OFFICIAL_WORK_CARD_KINDS as readonly string[]).includes(value)
  ) {
    return value as OfficialWorkCardKind;
  }
  throw new Error(`Unsupported official work-card kind: ${String(value)}`);
}

function normalizeOfficialWorkCard(value: unknown): OfficialWorkCard {
  const record = requireRecord(value, 'official-work-card');
  const display = requireRecord(record.display, 'official-work-card.display');
  return {
    id: requireNumber(record, 'id', 'official-work-card'),
    rowVersion: requireNumber(record, 'row_version', 'official-work-card'),
    kind: normalizeOfficialWorkCardKind(record.kind),
    assigneeStaffId: requireNumber(record, 'assignee_staff_id', 'official-work-card'),
    assigneeStaffName: displayName(
      requireString(record, 'assignee_staff_name', 'official-work-card'),
    ),
    title: requireString(display, 'work_title', 'official-work-card.display'),
    targetName: displayName(
      requireString(display, 'target_name', 'official-work-card.display'),
    ),
    detail: requireString(display, 'detail', 'official-work-card.display'),
    dueDate: requireString(display, 'due_date', 'official-work-card.display'),
    dDay: requireNumber(display, 'd_day', 'official-work-card.display'),
  };
}

export function normalizeOfficialWorkCardCollection(
  payload: unknown,
): OfficialWorkCardCollection {
  const record = requireRecord(payload, 'official-work-card-list');
  return {
    asOfDate: requireString(record, 'as_of_date', 'official-work-card-list'),
    groups: requireArray(record, 'groups', 'official-work-card-list').map((value) => {
      const group = requireRecord(value, 'official-work-card-group');
      return {
        staffId: requireNumber(group, 'staff_id', 'official-work-card-group'),
        staffName: displayName(
          requireString(group, 'staff_name', 'official-work-card-group'),
        ),
        cards: requireArray(group, 'items', 'official-work-card-group').map(
          normalizeOfficialWorkCard,
        ),
      };
    }),
  };
}

function normalizePersonalTodo(value: unknown): PersonalTodo {
  const record = requireRecord(value, 'personal-todo');
  return {
    id: requireNumber(record, 'id', 'personal-todo'),
    title: requireString(record, 'title', 'personal-todo'),
    completed: requireBoolean(record, 'completed', 'personal-todo'),
    order: requireNumber(record, 'sort_order', 'personal-todo'),
    rowVersion: requireNumber(record, 'row_version', 'personal-todo'),
  };
}

export function normalizePersonalTodoList(payload: unknown): PersonalTodoList {
  const record = requireRecord(payload, 'personal-todo-list');
  return {
    listRevision: requireNumber(record, 'list_revision', 'personal-todo-list'),
    items: requireArray(record, 'items', 'personal-todo-list').map(normalizePersonalTodo),
  };
}

function normalizeScheduleItem(value: unknown): ScheduleItem {
  const record = requireRecord(value, 'schedule');
  return {
    id: requireNumber(record, 'id', 'schedule'),
    scheduleMonth: requireString(record, 'schedule_month', 'schedule'),
    recipientId: requireNumber(record, 'recipient_id', 'schedule'),
    assignedStaff: requireArray(record, 'assigned_staff', 'schedule').map((assigned) => {
      const assignedRecord = requireRecord(assigned, 'schedule.assigned_staff');
      return {
        staffId: requireNumber(assignedRecord, 'staff_id', 'schedule.assigned_staff'),
        employmentId: requireNumber(
          assignedRecord,
          'employment_id',
          'schedule.assigned_staff',
        ),
      };
    }),
    serviceTypeId: requireNumber(record, 'service_type_id', 'schedule'),
    startsAtUtc: requireString(record, 'starts_at_utc', 'schedule'),
    endsAtUtc: requireString(record, 'ends_at_utc', 'schedule'),
    rowVersion: requireNumber(record, 'row_version', 'schedule'),
  };
}

export function normalizeScheduleMonthSnapshot(payload: unknown): ScheduleMonthSnapshot {
  const record = requireRecord(payload, 'schedule-month');
  if (!Object.prototype.hasOwnProperty.call(record, 'finalized_at_utc')) {
    throw new Error('Invalid schedule-month.finalized_at_utc');
  }
  const rawFinalizedAtUtc = record.finalized_at_utc;
  if (rawFinalizedAtUtc !== null && typeof rawFinalizedAtUtc !== 'string') {
    throw new Error('Invalid schedule-month.finalized_at_utc');
  }
  return {
    scheduleMonth: requireString(record, 'schedule_month', 'schedule-month'),
    finalized: requireBoolean(record, 'finalized', 'schedule-month'),
    finalizedAtUtc: rawFinalizedAtUtc as string | null,
    rowVersion: requireNumber(record, 'row_version', 'schedule-month'),
    items: requireArray(record, 'items', 'schedule-month').map(normalizeScheduleItem),
  };
}

export function projectScheduleMonthSnapshot(
  snapshot: ScheduleMonthSnapshot,
  filter: ScheduleSnapshotFilter = {},
): ScheduleMonthSnapshot {
  const { recipientId, staffId } = filter;
  if (recipientId === undefined && staffId === undefined) {
    return snapshot;
  }
  return {
    scheduleMonth: snapshot.scheduleMonth,
    finalized: snapshot.finalized,
    finalizedAtUtc: snapshot.finalizedAtUtc,
    rowVersion: snapshot.rowVersion,
    items: snapshot.items.filter((item) => {
      if (recipientId !== undefined && item.recipientId !== recipientId) {
        return false;
      }
      if (
        staffId !== undefined
        && !item.assignedStaff.some((assigned) => assigned.staffId === staffId)
      ) {
        return false;
      }
      return true;
    }),
  };
}

function normalizeServicePlanNotice(value: unknown): ServicePlanNotice {
  const record = requireRecord(value, 'service-plan-notice');
  const rawInvalidatedAtUtc = record.invalidated_at_utc;
  const rawReplacementId = record.replacement_service_plan_notice_id;
  if (rawInvalidatedAtUtc !== null && typeof rawInvalidatedAtUtc !== 'string') {
    throw new Error('Invalid service-plan-notice.invalidated_at_utc');
  }
  if (
    rawReplacementId !== null
    && (typeof rawReplacementId !== 'number' || !Number.isFinite(rawReplacementId))
  ) {
    throw new Error('Invalid service-plan-notice.replacement_service_plan_notice_id');
  }
  const invalidatedAtUtc = rawInvalidatedAtUtc as string | null;
  const replacementId = rawReplacementId as number | null;
  return {
    id: requireNumber(record, 'id', 'service-plan-notice'),
    recipientId: requireNumber(record, 'recipient_id', 'service-plan-notice'),
    recipientContractId: requireNumber(
      record,
      'recipient_contract_id',
      'service-plan-notice',
    ),
    notificationDate: requireString(record, 'notification_date', 'service-plan-notice'),
    appliedStartDate: requireString(record, 'applied_start_date', 'service-plan-notice'),
    appliedEndDate: requireString(record, 'applied_end_date', 'service-plan-notice'),
    invalidatedAtUtc,
    replacementServicePlanNoticeId: replacementId,
    rowVersion: requireNumber(record, 'row_version', 'service-plan-notice'),
  };
}

export function normalizeServicePlanNoticeHistory(payload: unknown): ServicePlanNoticeHistory {
  const record = requireRecord(payload, 'service-plan-notice-history');
  return {
    items: requireArray(record, 'items', 'service-plan-notice-history').map(
      normalizeServicePlanNotice,
    ),
  };
}

function latestFromDetails(error: ApiError): unknown {
  return error.details?.latest;
}

function throwTodoConflict(error: unknown): never {
  if (error instanceof ApiError && error.status === 409) {
    const latest = latestFromDetails(error);
    throw new W2ConflictError(error.message || '다른 창에서 할 일이 먼저 변경되었습니다.', {
      ...(latest !== undefined ? { latestTodoList: normalizePersonalTodoList(latest) } : {}),
    });
  }
  throw error;
}

function throwScheduleConflict(error: unknown): never {
  if (error instanceof ApiError && error.status === 409) {
    const latest = latestFromDetails(error);
    throw new W2ConflictError(error.message || '다른 요청이 일정을 먼저 변경했습니다.', {
      ...(latest !== undefined
        ? { latestScheduleSnapshot: normalizeScheduleMonthSnapshot(latest) }
        : {}),
    });
  }
  throw error;
}

function throwServicePlanConflict(error: unknown): never {
  if (error instanceof ApiError && error.status === 409) {
    const latest = latestFromDetails(error);
    throw new W2ConflictError(error.message || '다른 요청이 계획서를 먼저 변경했습니다.', {
      ...(latest !== undefined
        ? { latestServicePlanHistory: normalizeServicePlanNoticeHistory(latest) }
        : {}),
    });
  }
  throw error;
}

function servicePlanPayload(input: ServicePlanNoticeInput): Record<string, unknown> {
  return {
    recipient_contract_id: input.recipientContractId,
    notification_date: input.notificationDate,
    applied_start_date: input.appliedStartDate,
    ...(input.appliedEndDate === undefined
      ? {}
      : { applied_end_date: input.appliedEndDate }),
  };
}

export function listServicePlanNotices(
  recipientId: number | string,
  signal?: AbortSignal,
): Promise<ServicePlanNoticeHistory> {
  return apiRequest<unknown>(W2_ENDPOINTS.servicePlanNotices(recipientId), {
    method: 'GET',
    signal,
  }).then(normalizeServicePlanNoticeHistory);
}

export function createServicePlanNotice(
  recipientId: number | string,
  input: ServicePlanNoticeInput,
): Promise<ServicePlanNotice> {
  return apiRequest<unknown>(W2_ENDPOINTS.servicePlanNotices(recipientId), {
    method: 'POST',
    body: JSON.stringify(servicePlanPayload(input)),
  }).then(normalizeServicePlanNotice);
}

export async function replaceServicePlanNotice(
  recipientId: number | string,
  noticeId: number,
  expectedRowVersion: number,
  input: ServicePlanNoticeInput,
): Promise<ServicePlanNotice> {
  try {
    return await apiRequest<unknown>(
      `${W2_ENDPOINTS.servicePlanNotices(recipientId)}/${encodeURIComponent(noticeId)}`,
      {
        method: 'PUT',
        body: JSON.stringify({
          ...servicePlanPayload(input),
          expected_row_version: expectedRowVersion,
        }),
      },
    ).then(normalizeServicePlanNotice);
  } catch (error) {
    throwServicePlanConflict(error);
  }
}

export function listOfficialWorkCards(
  signal?: AbortSignal,
): Promise<OfficialWorkCardCollection> {
  return apiRequest<unknown>(W2_ENDPOINTS.officialWorkCards, { method: 'GET', signal }).then(
    normalizeOfficialWorkCardCollection,
  );
}

export function closeOfficialWorkCard(
  id: number,
  expectedRowVersion: number,
): Promise<OfficialWorkCardCollection> {
  return apiRequest<unknown>(
    `${W2_ENDPOINTS.officialWorkCards}/${encodeURIComponent(id)}/close`,
    {
      method: 'POST',
      body: JSON.stringify({ expected_row_version: expectedRowVersion }),
    },
  ).then(normalizeOfficialWorkCardCollection);
}

export function normalizeOfficialWorkCardEligibleAssignees(
  payload: unknown,
): OfficialWorkCardEligibleAssigneeList {
  const record = requireRecord(payload, 'official-work-card-eligible-assignees');
  return {
    asOfDate: requireString(record, 'as_of_date', 'official-work-card-eligible-assignees'),
    items: requireArray(record, 'items', 'official-work-card-eligible-assignees').map((value) => {
      const item = requireRecord(value, 'official-work-card-eligible-assignee');
      return {
        staffId: requireNumber(item, 'staff_id', 'official-work-card-eligible-assignee'),
        staffName: displayName(
          requireString(item, 'staff_name', 'official-work-card-eligible-assignee'),
        ),
      };
    }),
  };
}

function throwOfficialCardConflict(error: unknown): never {
  if (error instanceof ApiError && error.status === 409) {
    const latest = latestFromDetails(error);
    throw new W2ConflictError(error.message || '다른 요청이 업무카드를 먼저 변경했습니다.', {
      ...(latest !== undefined
        ? { latestOfficialWorkCards: normalizeOfficialWorkCardCollection(latest) }
        : {}),
    });
  }
  throw error;
}

export function listOfficialWorkCardEligibleAssignees(
  signal?: AbortSignal,
): Promise<OfficialWorkCardEligibleAssigneeList> {
  return apiRequest<unknown>(W2_ENDPOINTS.officialWorkCardEligibleAssignees, {
    method: 'GET',
    signal,
  }).then(normalizeOfficialWorkCardEligibleAssignees);
}

export async function reassignOfficialWorkCard(
  id: number,
  expectedRowVersion: number,
  assigneeStaffId: number,
): Promise<OfficialWorkCardCollection> {
  try {
    return await apiRequest<unknown>(
      `${W2_ENDPOINTS.officialWorkCards}/${encodeURIComponent(id)}/reassign`,
      {
        method: 'POST',
        body: JSON.stringify({
          expected_row_version: expectedRowVersion,
          assignee_staff_id: assigneeStaffId,
        }),
      },
    ).then(normalizeOfficialWorkCardCollection);
  } catch (error) {
    throwOfficialCardConflict(error);
  }
}

export function listPersonalTodos(signal?: AbortSignal): Promise<PersonalTodoList> {
  return apiRequest<unknown>(W2_ENDPOINTS.personalTodos, { method: 'GET', signal }).then(
    normalizePersonalTodoList,
  );
}

export async function createPersonalTodo(
  title: string,
  expectedListRevision: number,
): Promise<PersonalTodoList> {
  try {
    return await apiRequest<unknown>(W2_ENDPOINTS.personalTodos, {
      method: 'POST',
      body: JSON.stringify({
        title: title.trim(),
        expected_list_revision: expectedListRevision,
      }),
    }).then(normalizePersonalTodoList);
  } catch (error) {
    throwTodoConflict(error);
  }
}

export async function updatePersonalTodo(
  todo: Pick<PersonalTodo, 'id' | 'rowVersion'>,
  expectedListRevision: number,
  patch: { title?: string; completed?: boolean },
): Promise<PersonalTodoList> {
  try {
    return await apiRequest<unknown>(
      `${W2_ENDPOINTS.personalTodos}/${encodeURIComponent(todo.id)}`,
      {
        method: 'PATCH',
        body: JSON.stringify({
          expected_list_revision: expectedListRevision,
          expected_row_version: todo.rowVersion,
          ...(patch.title !== undefined ? { title: patch.title.trim() } : {}),
          ...(patch.completed !== undefined ? { completed: patch.completed } : {}),
        }),
      },
    ).then(normalizePersonalTodoList);
  } catch (error) {
    throwTodoConflict(error);
  }
}

export async function deletePersonalTodo(
  todo: Pick<PersonalTodo, 'id' | 'rowVersion'>,
  expectedListRevision: number,
): Promise<PersonalTodoList> {
  try {
    return await apiRequest<unknown>(
      `${W2_ENDPOINTS.personalTodos}/${encodeURIComponent(todo.id)}`,
      {
        method: 'DELETE',
        body: JSON.stringify({
          expected_list_revision: expectedListRevision,
          expected_row_version: todo.rowVersion,
        }),
      },
    ).then(normalizePersonalTodoList);
  } catch (error) {
    throwTodoConflict(error);
  }
}

export async function reorderPersonalTodos(
  orderedIds: readonly number[],
  expectedListRevision: number,
): Promise<PersonalTodoList> {
  try {
    return await apiRequest<unknown>(W2_ENDPOINTS.personalTodoReorder, {
      method: 'POST',
      body: JSON.stringify({
        expected_list_revision: expectedListRevision,
        ordered_ids: orderedIds,
      }),
    }).then(normalizePersonalTodoList);
  } catch (error) {
    throwTodoConflict(error);
  }
}

function scheduleQuery(params: ScheduleListParams): string {
  const query = new URLSearchParams({ month: params.month });
  if (params.recipientId !== undefined) {
    query.set('recipient_id', String(params.recipientId));
  }
  if (params.staffId !== undefined) query.set('staff_id', String(params.staffId));
  return `${W2_ENDPOINTS.schedules}?${query.toString()}`;
}

export async function listSchedules(
  params: ScheduleListParams,
): Promise<ScheduleMonthSnapshot> {
  const payload = await apiRequest<unknown>(scheduleQuery(params), {
    method: 'GET',
    signal: params.signal,
  });
  return normalizeScheduleMonthSnapshot(payload);
}

export async function createSchedule(
  input: ScheduleCreateInput,
): Promise<ScheduleMonthSnapshot> {
  try {
    return await apiRequest<unknown>(W2_ENDPOINTS.schedules, {
      method: 'POST',
      body: JSON.stringify({
        schedule_month: input.scheduleMonth,
        recipient_id: input.recipientId,
        assigned_staff: input.assignedStaff.map((assigned) => ({
          staff_id: assigned.staffId,
          employment_id: assigned.employmentId,
        })),
        service_type_id: input.serviceTypeId,
        starts_at_utc: input.startsAtUtc,
        ends_at_utc: input.endsAtUtc,
        expected_month_row_version: input.expectedMonthRowVersion,
      }),
    }).then(normalizeScheduleMonthSnapshot);
  } catch (error) {
    throwScheduleConflict(error);
  }
}

export async function replaceSchedule(
  id: number,
  input: ScheduleReplaceInput,
): Promise<ScheduleMonthSnapshot> {
  try {
    return await apiRequest<unknown>(
      `${W2_ENDPOINTS.schedules}/${encodeURIComponent(id)}`,
      {
        method: 'PUT',
        body: JSON.stringify({
          expected_month_row_version: input.expectedMonthRowVersion,
          expected_row_version: input.expectedRowVersion,
          recipient_id: input.recipientId,
          assigned_staff: input.assignedStaff.map((assigned) => ({
            staff_id: assigned.staffId,
            employment_id: assigned.employmentId,
          })),
          service_type_id: input.serviceTypeId,
          starts_at_utc: input.startsAtUtc,
          ends_at_utc: input.endsAtUtc,
        }),
      },
    ).then(normalizeScheduleMonthSnapshot);
  } catch (error) {
    throwScheduleConflict(error);
  }
}

export async function deleteSchedule(
  id: number,
  input: ScheduleDeleteInput,
): Promise<ScheduleMonthSnapshot> {
  try {
    return await apiRequest<unknown>(
      `${W2_ENDPOINTS.schedules}/${encodeURIComponent(id)}`,
      {
        method: 'DELETE',
        body: JSON.stringify({
          expected_month_row_version: input.expectedMonthRowVersion,
          expected_row_version: input.expectedRowVersion,
        }),
      },
    ).then(normalizeScheduleMonthSnapshot);
  } catch (error) {
    throwScheduleConflict(error);
  }
}

export async function finalizeScheduleMonth(
  scheduleMonth: string,
  expectedMonthRowVersion: number,
): Promise<ScheduleMonthSnapshot> {
  try {
    return await apiRequest<unknown>(W2_ENDPOINTS.scheduleMonthFinalize(scheduleMonth), {
      method: 'POST',
      body: JSON.stringify({ expected_month_row_version: expectedMonthRowVersion }),
    }).then(normalizeScheduleMonthSnapshot);
  } catch (error) {
    throwScheduleConflict(error);
  }
}
