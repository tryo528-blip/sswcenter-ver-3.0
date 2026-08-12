import { describe, it, expect, beforeEach } from 'vitest';
import {
  createTaskInstance,
  isRoleEligibleForTemplate,
  updateSubtaskStatus,
  updateDeadline,
  reorderTaskInstance,
  addAttachment,
  removeAttachment,
  type TaskInstance,
  type StepAttachment,
  type SubtaskStatus,
} from '../components/dashboard/taskInstances';
import { getTaskTemplate } from '../components/dashboard/taskTemplates';

// ── helpers ────────────────────────────────────────────────────

function makeValidInput(overrides: Partial<{
  recipientTarget: string;
  templateId: string;
  assignee: string;
  assigneeRole: 'social-worker' | 'center-manager';
  deadline: string | undefined;
  order: number;
}> = {}) {
  return {
    recipientTarget: '수급자-홍길동',
    templateId: 'recipient-recognition-renewal',
    assignee: '사회복지사-김철수',
    assigneeRole: 'center-manager' as const,
    ...overrides,
  };
}

// ════════════════════════════════════════════════════════════════
//  createTaskInstance
// ════════════════════════════════════════════════════════════════

describe('createTaskInstance', () => {
  it('creates a task instance with all steps pending and correct subtask count', () => {
    const inst = createTaskInstance(makeValidInput());

    expect(inst.id).toBeTruthy();
    expect(typeof inst.id).toBe('string');
    expect(inst.recipientTarget).toBe('수급자-홍길동');
    expect(inst.templateId).toBe('recipient-recognition-renewal');
    expect(inst.assignee).toBe('사회복지사-김철수');
    expect(inst.assigneeRole).toBe('center-manager');
    expect(inst.order).toBe(0);

    const template = getTaskTemplate('recipient-recognition-renewal')!;
    expect(inst.subtasks).toHaveLength(template.steps.length);

    for (let i = 0; i < inst.subtasks.length; i++) {
      const s = inst.subtasks[i];
      expect(s.stepIndex).toBe(i);
      expect(s.status).toBe('pending');
      expect(s.attachments).toEqual([]);
    }
  });

  it('preserves subtask order in the stored stepIndex values', () => {
    const inst = createTaskInstance(makeValidInput({ templateId: 'staff-resignation' }));

    expect(inst.subtasks).toHaveLength(3);
    expect(inst.subtasks.map((subtask) => subtask.stepIndex)).toEqual([0, 1, 2]);
  });

  it('accepts an explicit order', () => {
    const inst = createTaskInstance(makeValidInput({ order: 42 }));
    expect(inst.order).toBe(42);
  });

  it('accepts a valid deadline', () => {
    const inst = createTaskInstance(
      makeValidInput({ deadline: '2026-12-31' }),
    );
    expect(inst.deadline).toBe('2026-12-31');
  });

  it('omits deadline when not provided', () => {
    const inst = createTaskInstance(makeValidInput({ deadline: undefined }));
    expect(inst.deadline).toBeUndefined();
  });

  // ── validation ─────────────────────────────────────────────

  it('throws on empty recipientTarget', () => {
    expect(() => createTaskInstance(makeValidInput({ recipientTarget: '' }))).toThrow(
      'recipientTarget must be a non-empty string',
    );
    expect(() => createTaskInstance(makeValidInput({ recipientTarget: '   ' }))).toThrow(
      'recipientTarget must be a non-empty string',
    );
  });

  it('throws on empty assignee', () => {
    expect(() => createTaskInstance(makeValidInput({ assignee: '' }))).toThrow(
      'assignee must be a non-empty string',
    );
    expect(() => createTaskInstance(makeValidInput({ assignee: '   ' }))).toThrow(
      'assignee must be a non-empty string',
    );
  });

  it('throws on unknown template', () => {
    expect(() =>
      createTaskInstance(makeValidInput({ templateId: 'nonexistent' })),
    ).toThrow('Unknown template: nonexistent');
  });

  it('throws on unknown role', () => {
    expect(() =>
      createTaskInstance(
        makeValidInput({ assigneeRole: 'nobody' as 'center-manager' }),
      ),
    ).toThrow('Unknown role: nobody');
  });

  it('throws when role is ineligible for template', () => {
    // social-worker cannot use template 6 (staff-new-onboarding)
    expect(() =>
      createTaskInstance(
        makeValidInput({
          templateId: 'staff-new-onboarding',
          assigneeRole: 'social-worker',
        }),
      ),
    ).toThrow(
      'Role social-worker is not allowed for template staff-new-onboarding',
    );
  });

  it('throws on invalid deadline format', () => {
    expect(() =>
      createTaskInstance(makeValidInput({ deadline: 'next Monday' })),
    ).toThrow('Invalid deadline: next Monday');

    expect(() =>
      createTaskInstance(makeValidInput({ deadline: '2026-13-01' })),
    ).toThrow('Invalid deadline: 2026-13-01');
  });

  it('throws on non-finite order', () => {
    expect(() =>
      createTaskInstance(makeValidInput({ order: NaN })),
    ).toThrow('order must be a finite number');

    expect(() =>
      createTaskInstance(makeValidInput({ order: Infinity })),
    ).toThrow('order must be a finite number');
  });

  it('throws on null order (only undefined may default to 0)', () => {
    expect(() =>
      createTaskInstance(
        makeValidInput({ order: null as unknown as number }),
      ),
    ).toThrow('order must be a finite number, got null');
  });
});

// ════════════════════════════════════════════════════════════════
//  isRoleEligibleForTemplate
// ════════════════════════════════════════════════════════════════

describe('isRoleEligibleForTemplate', () => {
  // Templates 1–5: both roles allowed
  const templates1to5 = [
    'recipient-recognition-renewal',
    'recipient-contract-renewal',
    'recipient-plan-renewal',
    'recipient-new',
    'staff-new-preparation',
  ] as const;

  // Templates 6–8: center-manager only
  const templates6to8 = [
    'staff-new-onboarding',
    'staff-resignation',
    'staff-recipient-termination',
  ] as const;

  describe('social-worker', () => {
    it('is eligible for templates 1–5', () => {
      for (const id of templates1to5) {
        expect(isRoleEligibleForTemplate('social-worker', id)).toBe(true);
      }
    });

    it('is NOT eligible for templates 6–8', () => {
      for (const id of templates6to8) {
        expect(isRoleEligibleForTemplate('social-worker', id)).toBe(false);
      }
    });
  });

  describe('center-manager', () => {
    it('is eligible for templates 1–5', () => {
      for (const id of templates1to5) {
        expect(isRoleEligibleForTemplate('center-manager', id)).toBe(true);
      }
    });

    it('is eligible for templates 6–8', () => {
      for (const id of templates6to8) {
        expect(isRoleEligibleForTemplate('center-manager', id)).toBe(true);
      }
    });
  });

  it('returns false for unknown template', () => {
    expect(isRoleEligibleForTemplate('center-manager', 'fantasy')).toBe(false);
    expect(isRoleEligibleForTemplate('social-worker', '')).toBe(false);
  });
});

// ════════════════════════════════════════════════════════════════
//  updateSubtaskStatus
// ════════════════════════════════════════════════════════════════

describe('updateSubtaskStatus', () => {
  let inst: TaskInstance;

  beforeEach(() => {
    inst = createTaskInstance(makeValidInput());
  });

  it('updates a step from pending to completed', () => {
    const updated = updateSubtaskStatus(inst, 0, 'completed');
    expect(updated.subtasks[0].status).toBe('completed');
    // other steps unchanged
    for (let i = 1; i < updated.subtasks.length; i++) {
      expect(updated.subtasks[i].status).toBe('pending');
    }
  });

  it('does not mutate the original instance', () => {
    const frozen = Object.freeze(inst);
    const updated = updateSubtaskStatus(frozen as TaskInstance, 0, 'completed');
    expect(updated).not.toBe(frozen);
    expect(updated.subtasks).not.toBe(frozen.subtasks);
    expect(frozen.subtasks[0].status).toBe('pending');
    expect(updated.subtasks[0].status).toBe('completed');
  });

  it('returns structurally equal instance when status unchanged', () => {
    const updated = updateSubtaskStatus(inst, 0, 'pending');
    // value equality, not reference equality
    expect(updated.subtasks[0].status).toBe('pending');
    expect(updated).not.toBe(inst);
  });

  it('throws on invalid step index', () => {
    expect(() => updateSubtaskStatus(inst, -1, 'completed')).toThrow(
      'Invalid step index: -1',
    );
    expect(() =>
      updateSubtaskStatus(inst, inst.subtasks.length, 'completed'),
    ).toThrow(`Invalid step index: ${inst.subtasks.length}`);
  });

  it('throws on invalid status', () => {
    expect(() =>
      updateSubtaskStatus(inst, 0, 'deleted' as SubtaskStatus),
    ).toThrow('Invalid subtask status: deleted');
    expect(() =>
      updateSubtaskStatus(inst, 0, '' as SubtaskStatus),
    ).toThrow('Invalid subtask status:');
  });

  it('throws on malformed instance whose stored stepIndex does not match position', () => {
    // Construct a runtime TaskInstance with discontinuous / duplicate
    // stored stepIndex values.  Positional targeting + the validation
    // inside assertValidStepIndex must reject this.
    const malformed: TaskInstance = {
      ...createTaskInstance(makeValidInput()),
      subtasks: [
        { stepIndex: 0, status: 'pending', attachments: [] },
        { stepIndex: 0, status: 'pending', attachments: [] }, // duplicate
        { stepIndex: 2, status: 'pending', attachments: [] },
      ],
    };

    // position 1 is inconsistent → should throw
    expect(() => updateSubtaskStatus(malformed, 1, 'completed')).toThrow(
      'Malformed instance: subtask at position 1 has stored stepIndex 0',
    );

    // position 0 is consistent → should succeed and only affect position 0
    const updated = updateSubtaskStatus(malformed, 0, 'completed');
    expect(updated.subtasks[0].status).toBe('completed');
    // duplicate stepIndex at position 1 must NOT be affected
    expect(updated.subtasks[1].status).toBe('pending');
    expect(updated.subtasks[2].status).toBe('pending');
  });
});

// ════════════════════════════════════════════════════════════════
//  updateDeadline
// ════════════════════════════════════════════════════════════════

describe('updateDeadline', () => {
  let inst: TaskInstance;

  beforeEach(() => {
    inst = createTaskInstance(makeValidInput({ deadline: undefined }));
  });

  it('sets a deadline when previously absent', () => {
    const updated = updateDeadline(inst, '2026-06-15');
    expect(updated.deadline).toBe('2026-06-15');
  });

  it('changes an existing deadline', () => {
    const withDeadline = createTaskInstance(
      makeValidInput({ deadline: '2026-01-01' }),
    );
    const updated = updateDeadline(withDeadline, '2026-12-31');
    expect(updated.deadline).toBe('2026-12-31');
  });

  it('removes the deadline when passed undefined', () => {
    const withDeadline = createTaskInstance(
      makeValidInput({ deadline: '2026-01-01' }),
    );
    const updated = updateDeadline(withDeadline, undefined);
    expect(updated.deadline).toBeUndefined();
    expect('deadline' in updated).toBe(false);
  });

  it('does not mutate the original instance', () => {
    const frozen = Object.freeze(inst);
    const updated = updateDeadline(frozen as TaskInstance, '2026-06-15');
    expect(updated).not.toBe(frozen);
    expect((frozen as TaskInstance).deadline).toBeUndefined();
  });

  it('throws on invalid deadline format', () => {
    expect(() => updateDeadline(inst, 'bad')).toThrow('Invalid deadline: bad');
    expect(() => updateDeadline(inst, '2026-02-30')).toThrow(
      'Invalid deadline: 2026-02-30',
    );
  });

  it('removing deadline is idempotent when already absent', () => {
    const updated = updateDeadline(inst, undefined);
    expect(updated.deadline).toBeUndefined();
    expect('deadline' in updated).toBe(false);
  });
});

// ════════════════════════════════════════════════════════════════
//  reorderTaskInstance
// ════════════════════════════════════════════════════════════════

describe('reorderTaskInstance', () => {
  let inst: TaskInstance;

  beforeEach(() => {
    inst = createTaskInstance(makeValidInput({ order: 10 }));
  });

  it('changes the order to a new value', () => {
    const updated = reorderTaskInstance(inst, 99);
    expect(updated.order).toBe(99);
  });

  it('does not mutate the original instance', () => {
    const frozen = Object.freeze(inst);
    const updated = reorderTaskInstance(frozen as TaskInstance, 5);
    expect(updated).not.toBe(frozen);
    expect(frozen.order).toBe(10);
  });

  it('accepts zero and negative numbers as valid sort positions', () => {
    const zero = reorderTaskInstance(inst, 0);
    expect(zero.order).toBe(0);

    const neg = reorderTaskInstance(inst, -3);
    expect(neg.order).toBe(-3);
  });

  it('throws on NaN or Infinity', () => {
    expect(() => reorderTaskInstance(inst, NaN)).toThrow(
      'order must be a finite number',
    );
    expect(() => reorderTaskInstance(inst, Infinity)).toThrow(
      'order must be a finite number',
    );
  });
});

// ════════════════════════════════════════════════════════════════
//  addAttachment / removeAttachment
// ════════════════════════════════════════════════════════════════

describe('attachments', () => {
  let inst: TaskInstance;

  beforeEach(() => {
    inst = createTaskInstance(makeValidInput());
  });

  describe('addAttachment', () => {
    it('adds an attachment to a step', () => {
      const updated = addAttachment(inst, 0, {
        id: 'att-1',
        name: '인정서.pdf',
        url: '/files/att-1',
      });

      expect(updated.subtasks[0].attachments).toHaveLength(1);
      expect(updated.subtasks[0].attachments[0]).toEqual({
        id: 'att-1',
        name: '인정서.pdf',
        url: '/files/att-1',
      });
      // other steps unchanged
      for (let i = 1; i < updated.subtasks.length; i++) {
        expect(updated.subtasks[i].attachments).toEqual([]);
      }
    });

    it('appends multiple attachments to the same step', () => {
      let updated = addAttachment(inst, 0, {
        id: 'a1',
        name: 'file1.png',
        url: '/f1',
      });
      updated = addAttachment(updated, 0, {
        id: 'a2',
        name: 'file2.png',
        url: '/f2',
      });

      expect(updated.subtasks[0].attachments).toHaveLength(2);
      expect(updated.subtasks[0].attachments.map((a) => a.id)).toEqual([
        'a1',
        'a2',
      ]);
    });

    it('does not mutate the original instance', () => {
      const frozen = Object.freeze(inst);
      const updated = addAttachment(frozen as TaskInstance, 0, {
        id: 'att-x',
        name: 'x.pdf',
        url: '/x',
      });
      expect(updated).not.toBe(frozen);
      expect(frozen.subtasks[0].attachments).toEqual([]);
    });

    it('throws on invalid step index', () => {
      expect(() =>
        addAttachment(inst, -1, { id: 'a', name: 'n', url: '/u' }),
      ).toThrow('Invalid step index: -1');
    });

    it('throws on empty attachment fields', () => {
      expect(() =>
        addAttachment(inst, 0, { id: '', name: 'n', url: '/u' }),
      ).toThrow('attachment.id must be a non-empty string');

      expect(() =>
        addAttachment(inst, 0, { id: 'a', name: '', url: '/u' }),
      ).toThrow('attachment.name must be a non-empty string');

      expect(() =>
        addAttachment(inst, 0, { id: 'a', name: 'n', url: '' }),
      ).toThrow('attachment.url must be a non-empty string');
    });

    it('throws when attachment fields are undefined', () => {
      expect(() =>
        addAttachment(inst, 0, {
          id: undefined,
          name: 'n',
          url: '/u',
        } as unknown as StepAttachment),
      ).toThrow('attachment.id must be a non-empty string');

      expect(() =>
        addAttachment(inst, 0, {
          id: 'a',
          name: undefined,
          url: '/u',
        } as unknown as StepAttachment),
      ).toThrow('attachment.name must be a non-empty string');

      expect(() =>
        addAttachment(inst, 0, {
          id: 'a',
          name: 'n',
          url: undefined,
        } as unknown as StepAttachment),
      ).toThrow('attachment.url must be a non-empty string');
    });

    it('materializes prototype getters into a detached attachment snapshot', () => {
      class GetterAttachment {
        public idValue: string;
        public nameValue: string;
        public urlValue: string;

        constructor(
          idValue: string,
          nameValue: string,
          urlValue: string,
        ) {
          this.idValue = idValue;
          this.nameValue = nameValue;
          this.urlValue = urlValue;
        }

        get id(): string {
          return this.idValue;
        }

        get name(): string {
          return this.nameValue;
        }

        get url(): string {
          return this.urlValue;
        }
      }

      const source = new GetterAttachment('getter-id', 'getter.pdf', '/getter');
      const updated = addAttachment(inst, 0, source);

      expect(updated.subtasks[0].attachments[0]).toEqual({
        id: 'getter-id',
        name: 'getter.pdf',
        url: '/getter',
      });
      expect(Object.keys(updated.subtasks[0].attachments[0])).toEqual([
        'id',
        'name',
        'url',
      ]);

      source.idValue = 'changed-id';
      source.nameValue = 'changed.pdf';
      source.urlValue = '/changed';
      expect(updated.subtasks[0].attachments[0]).toEqual({
        id: 'getter-id',
        name: 'getter.pdf',
        url: '/getter',
      });
    });

    it('throws on malformed instance whose stored stepIndex does not match position', () => {
      const malformed: TaskInstance = {
        ...createTaskInstance(makeValidInput()),
        subtasks: [
          { stepIndex: 0, status: 'pending', attachments: [] },
          { stepIndex: 0, status: 'pending', attachments: [] }, // duplicate stepIndex
          { stepIndex: 2, status: 'pending', attachments: [] },
        ],
      };

      // position 1 is inconsistent → must throw
      expect(() =>
        addAttachment(malformed, 1, { id: 'a', name: 'n', url: '/u' }),
      ).toThrow(
        'Malformed instance: subtask at position 1 has stored stepIndex 0',
      );

      // position 0 is consistent → must succeed and target exactly position 0
      const updated = addAttachment(malformed, 0, {
        id: 'att-ok',
        name: 'ok.pdf',
        url: '/ok',
      });
      expect(updated.subtasks[0].attachments).toHaveLength(1);
      // position 1 must NOT have received the attachment
      expect(updated.subtasks[1].attachments).toEqual([]);
      expect(updated.subtasks[2].attachments).toEqual([]);
    });

    it('is immune to caller mutating the attachment object after the call', () => {
      const mutableAttachment = {
        id: 'att-mut',
        name: 'original-name.pdf',
        url: '/original-url',
      };

      const updated = addAttachment(inst, 0, mutableAttachment);

      // mutate the caller-owned object
      mutableAttachment.id = 'hacked-id';
      mutableAttachment.name = 'hacked-name.pdf';
      mutableAttachment.url = '/evil-url';

      // stored attachment must retain the values at call time
      expect(updated.subtasks[0].attachments).toHaveLength(1);
      expect(updated.subtasks[0].attachments[0]).toEqual({
        id: 'att-mut',
        name: 'original-name.pdf',
        url: '/original-url',
      });
    });
  });

  describe('removeAttachment', () => {
    it('removes an attachment by id', () => {
      let updated = addAttachment(inst, 0, {
        id: 'att-keep',
        name: 'keep.pdf',
        url: '/keep',
      });
      updated = addAttachment(updated, 0, {
        id: 'att-drop',
        name: 'drop.pdf',
        url: '/drop',
      });

      const after = removeAttachment(updated, 0, 'att-drop');
      expect(after.subtasks[0].attachments).toHaveLength(1);
      expect(after.subtasks[0].attachments[0].id).toBe('att-keep');
    });

    it('is a no-op when attachment id is not found', () => {
      let updated = addAttachment(inst, 0, {
        id: 'only',
        name: 'only.pdf',
        url: '/only',
      });
      const after = removeAttachment(updated, 0, 'ghost');
      expect(after.subtasks[0].attachments).toHaveLength(1);
      expect(after.subtasks[0].attachments[0].id).toBe('only');
    });

    it('does not mutate the original instance', () => {
      let updated = addAttachment(inst, 0, {
        id: 'att-1',
        name: 'f.pdf',
        url: '/f',
      });
      const frozen = Object.freeze(updated);
      const after = removeAttachment(frozen as TaskInstance, 0, 'att-1');
      expect(after).not.toBe(frozen);
      expect((frozen as TaskInstance).subtasks[0].attachments).toHaveLength(1);
    });

    it('throws on invalid step index', () => {
      expect(() => removeAttachment(inst, 99, 'x')).toThrow(
        'Invalid step index: 99',
      );
    });

    it('throws on empty attachmentId', () => {
      expect(() => removeAttachment(inst, 0, '')).toThrow(
        'attachmentId must be a non-empty string',
      );
    });

    it('throws on malformed instance whose stored stepIndex does not match position', () => {
      // Build a malformed instance with a duplicate stepIndex at position 1.
      const malformed: TaskInstance = {
        ...createTaskInstance(makeValidInput()),
        subtasks: [
          { stepIndex: 0, status: 'pending', attachments: [] },
          { stepIndex: 0, status: 'pending', attachments: [] }, // duplicate
          { stepIndex: 2, status: 'pending', attachments: [] },
        ],
      };

      // position 1 is inconsistent → must throw
      expect(() => removeAttachment(malformed, 1, 'any-id')).toThrow(
        'Malformed instance: subtask at position 1 has stored stepIndex 0',
      );

      // position 0 is consistent → must succeed and remove from position 0 only
      // First add an attachment at position 0 so we have something to remove.
      const withAtt = addAttachment(malformed, 0, {
        id: 'to-remove',
        name: 'rm.pdf',
        url: '/rm',
      });
      const afterRemove = removeAttachment(withAtt, 0, 'to-remove');
      expect(afterRemove.subtasks[0].attachments).toEqual([]);
      // position 1 must not be affected
      expect(afterRemove.subtasks[1].attachments).toEqual([]);
    });
  });
});

// ════════════════════════════════════════════════════════════════
//  full workflow smoke test
// ════════════════════════════════════════════════════════════════

describe('TaskInstance workflow', () => {
  it('handles a full lifecycle without mutation', () => {
    const original = createTaskInstance(
      makeValidInput({ templateId: 'recipient-new' }),
    );

    // complete first step
    const afterStep = updateSubtaskStatus(original, 0, 'completed');
    expect(afterStep.subtasks[0].status).toBe('completed');
    expect(original.subtasks[0].status).toBe('pending');

    // set deadline
    const withDeadline = updateDeadline(afterStep, '2026-10-10');
    expect(withDeadline.deadline).toBe('2026-10-10');
    expect(original.deadline).toBeUndefined();

    // reorder
    const reordered = reorderTaskInstance(withDeadline, 5);
    expect(reordered.order).toBe(5);
    expect(afterStep.order).toBe(0);

    // add attachment
    const withAtt = addAttachment(reordered, 0, {
      id: 'proof',
      name: 'proof.jpg',
      url: '/proof',
    });
    expect(withAtt.subtasks[0].attachments).toHaveLength(1);
    expect(reordered.subtasks[0].attachments).toHaveLength(0);

    // remove attachment
    const cleaned = removeAttachment(withAtt, 0, 'proof');
    expect(cleaned.subtasks[0].attachments).toHaveLength(0);

    // remove deadline
    const noDeadline = updateDeadline(cleaned, undefined);
    expect(noDeadline.deadline).toBeUndefined();

    // original untouched
    expect(original.subtasks[0].status).toBe('pending');
    expect(original.subtasks[0].attachments).toEqual([]);
    expect(original.deadline).toBeUndefined();
    expect(original.order).toBe(0);
  });
});
