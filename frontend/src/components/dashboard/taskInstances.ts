import { type TaskRole, getTaskTemplate } from './taskTemplates';

// ── types ──────────────────────────────────────────────────────

export type SubtaskStatus = 'pending' | 'completed';

export interface StepAttachment {
  readonly id: string;
  readonly name: string;
  readonly url: string;
}

export interface SubtaskState {
  readonly stepIndex: number;
  readonly status: SubtaskStatus;
  readonly attachments: readonly StepAttachment[];
}

export interface TaskInstance {
  readonly id: string;
  readonly recipientTarget: string;
  readonly templateId: string;
  readonly assignee: string;
  readonly assigneeRole: TaskRole;
  readonly subtasks: readonly SubtaskState[];
  readonly deadline?: string;
  readonly order: number;
}

export interface CreateTaskInstanceInput {
  recipientTarget: string;
  templateId: string;
  assignee: string;
  assigneeRole: TaskRole;
  deadline?: string;
  order?: number;
}

// ── helpers ────────────────────────────────────────────────────

const ISO_DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

function isValidISODate(v: string): boolean {
  if (!ISO_DATE_RE.test(v)) return false;
  const [y, m, d] = v.split('-').map(Number);
  const date = new Date(y, m - 1, d);
  return (
    !isNaN(date.getTime()) &&
    date.getFullYear() === y &&
    date.getMonth() === m - 1 &&
    date.getDate() === d
  );
}

function assertNonEmptyString(value: string, label: string): void {
  if (typeof value !== 'string' || value.trim().length === 0) {
    throw new Error(`${label} must be a non-empty string`);
  }
}

function assertValidRole(role: string): asserts role is TaskRole {
  if (role !== 'social-worker' && role !== 'center-manager') {
    throw new Error(`Unknown role: ${role}`);
  }
}

function assertValidStepIndex(instance: TaskInstance, stepIndex: number): void {
  if (!Number.isInteger(stepIndex) || stepIndex < 0 || stepIndex >= instance.subtasks.length) {
    throw new Error(
      `Invalid step index: ${stepIndex} (valid range: 0–${instance.subtasks.length - 1})`,
    );
  }
  // Defend against malformed instances whose stored stepIndex values
  // do not match their array positions (discontinuous / duplicate).
  if (instance.subtasks[stepIndex].stepIndex !== stepIndex) {
    throw new Error(
      `Malformed instance: subtask at position ${stepIndex} has stored stepIndex ${instance.subtasks[stepIndex].stepIndex}`,
    );
  }
}

// ── factory ────────────────────────────────────────────────────

/**
 * Create a new TaskInstance with every template step initialised as
 * `pending` and empty attachment lists.
 */
export function createTaskInstance(input: CreateTaskInstanceInput): TaskInstance {
  assertNonEmptyString(input.recipientTarget, 'recipientTarget');
  assertNonEmptyString(input.assignee, 'assignee');
  assertValidRole(input.assigneeRole);

  const template = getTaskTemplate(input.templateId);
  if (!template) {
    throw new Error(`Unknown template: ${input.templateId}`);
  }

  if (!isRoleEligibleForTemplate(input.assigneeRole, input.templateId)) {
    throw new Error(
      `Role ${input.assigneeRole} is not allowed for template ${input.templateId}`,
    );
  }

  if (input.deadline !== undefined) {
    if (typeof input.deadline !== 'string' || !isValidISODate(input.deadline)) {
      throw new Error(`Invalid deadline: ${input.deadline}`);
    }
  }

  if (input.order !== undefined) {
    if (typeof input.order !== 'number' || !Number.isFinite(input.order)) {
      throw new Error(`order must be a finite number, got ${input.order}`);
    }
  }
  const order = input.order ?? 0;

  const subtasks: SubtaskState[] = template.steps.map((_, i) => ({
    stepIndex: i,
    status: 'pending' as const,
    attachments: [],
  }));

  return {
    id: crypto.randomUUID(),
    recipientTarget: input.recipientTarget.trim(),
    templateId: input.templateId,
    assignee: input.assignee.trim(),
    assigneeRole: input.assigneeRole,
    subtasks,
    ...(input.deadline !== undefined ? { deadline: input.deadline } : {}),
    order,
  };
}

// ── role eligibility ──────────────────────────────────────────

/**
 * Returns true when `role` is permitted to act on the given template.
 *
 * Center-manager can perform templates 1–8; social-worker only 1–5.
 * Templates staff-new-onboarding, staff-resignation, and
 * staff-recipient-termination are center-manager-only.
 */
export function isRoleEligibleForTemplate(role: TaskRole, templateId: string): boolean {
  const template = getTaskTemplate(templateId);
  if (!template) return false;
  return template.allowedRoles.includes(role);
}

// ── immutable subtask status update ───────────────────────────

/**
 * Return a new TaskInstance with the status of one subtask changed.
 * The original instance is not mutated.
 */
export function updateSubtaskStatus(
  instance: TaskInstance,
  stepIndex: number,
  status: SubtaskStatus,
): TaskInstance {
  assertValidStepIndex(instance, stepIndex);

  if (status !== 'pending' && status !== 'completed') {
    throw new Error(`Invalid subtask status: ${status}`);
  }

  const updatedSubtasks = instance.subtasks.map((s, idx) =>
    idx === stepIndex ? { ...s, status } : s,
  );

  return { ...instance, subtasks: updatedSubtasks };
}

// ── optional deadline update ──────────────────────────────────

/**
 * Return a new TaskInstance with an updated deadline.
 * Pass `undefined` to remove the deadline entirely.
 */
export function updateDeadline(
  instance: TaskInstance,
  deadline: string | undefined,
): TaskInstance {
  if (deadline !== undefined) {
    if (typeof deadline !== 'string' || !isValidISODate(deadline)) {
      throw new Error(`Invalid deadline: ${deadline}`);
    }
    return { ...instance, deadline };
  }

  // remove the deadline key
  const { deadline: _removed, ...rest } = instance;
  return rest as TaskInstance;
}

// ── immutable reorder ─────────────────────────────────────────

/** Return a new TaskInstance with an updated sort order. */
export function reorderTaskInstance(instance: TaskInstance, newOrder: number): TaskInstance {
  if (typeof newOrder !== 'number' || !Number.isFinite(newOrder)) {
    throw new Error(`order must be a finite number, got ${newOrder}`);
  }
  return { ...instance, order: newOrder };
}

// ── optional attachments ──────────────────────────────────────

/**
 * Return a new TaskInstance with an attachment added to a subtask.
 * The attachment must have non-empty id, name, and url.
 */
export function addAttachment(
  instance: TaskInstance,
  stepIndex: number,
  attachment: StepAttachment,
): TaskInstance {
  assertValidStepIndex(instance, stepIndex);

  // Read the structural fields explicitly so prototype getters and class
  // instances become a detached value snapshot instead of an empty spread.
  const attachmentSnapshot: StepAttachment = {
    id: attachment.id,
    name: attachment.name,
    url: attachment.url,
  };
  assertNonEmptyString(attachmentSnapshot.id, 'attachment.id');
  assertNonEmptyString(attachmentSnapshot.name, 'attachment.name');
  assertNonEmptyString(attachmentSnapshot.url, 'attachment.url');

  const updatedSubtasks = instance.subtasks.map((s, idx) =>
    idx === stepIndex
      ? { ...s, attachments: [...s.attachments, attachmentSnapshot] }
      : s,
  );

  return { ...instance, subtasks: updatedSubtasks };
}

/**
 * Return a new TaskInstance with an attachment removed from a subtask.
 */
export function removeAttachment(
  instance: TaskInstance,
  stepIndex: number,
  attachmentId: string,
): TaskInstance {
  assertValidStepIndex(instance, stepIndex);
  assertNonEmptyString(attachmentId, 'attachmentId');

  const updatedSubtasks = instance.subtasks.map((s, idx) =>
    idx === stepIndex
      ? { ...s, attachments: s.attachments.filter((a) => a.id !== attachmentId) }
      : s,
  );

  return { ...instance, subtasks: updatedSubtasks };
}
