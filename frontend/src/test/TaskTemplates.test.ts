import { describe, expect, it } from 'vitest';
import {
  TASK_TEMPLATES,
  getTaskTemplate,
  type TaskTemplate,
  type TaskRole,
  type TaskStep,
} from '../components/dashboard/taskTemplates';

describe('TASK_TEMPLATES', () => {
  it('contains exactly 8 templates', () => {
    expect(TASK_TEMPLATES).toHaveLength(8);
  });

  it('has the correct id and title for every template', () => {
    const actual = TASK_TEMPLATES.map((t) => ({ id: t.id, title: t.title }));
    expect(actual).toEqual([
      { id: 'recipient-recognition-renewal', title: '인정서갱신' },
      { id: 'recipient-contract-renewal', title: '계약갱신' },
      { id: 'recipient-plan-renewal', title: '계획갱신' },
      { id: 'recipient-new', title: '신규수급자' },
      { id: 'staff-new-preparation', title: '신규직원입사자료준비' },
      { id: 'staff-new-onboarding', title: '신규직원업무' },
      { id: 'staff-resignation', title: '퇴사직원업무' },
      { id: 'staff-recipient-termination', title: '수급자종료' },
    ]);
  });
});

describe('recipient-recognition-renewal (인정서갱신)', () => {
  const template = getTaskTemplate('recipient-recognition-renewal')!;

  it('has 9 steps in correct order', () => {
    expect(template.steps).toHaveLength(9);
    expect(template.steps.map((s) => s.name)).toEqual([
      '인정서확보',
      '계약서작성',
      '계약- 공단등록',
      '계약- 고씨등록',
      '욕구-욕낙치',
      '지난계획평가',
      '새 계획서 통보',
      '일정등록-공단',
      '일정등록-고씨',
    ]);
  });
});

describe('recipient-contract-renewal (계약갱신)', () => {
  const template = getTaskTemplate('recipient-contract-renewal')!;

  it('has 8 steps', () => {
    expect(template.steps).toHaveLength(8);
  });

  it('excludes 인정서확보', () => {
    const names = template.steps.map((s) => s.name);
    expect(names).not.toContain('인정서확보');
  });

  it('preserves the remaining order from 인정서갱신 without 인정서확보', () => {
    const recognition = getTaskTemplate('recipient-recognition-renewal')!;
    const withoutFirst = recognition.steps.slice(1).map((s) => s.name);
    expect(template.steps.map((s) => s.name)).toEqual(withoutFirst);
  });
});

describe('recipient-plan-renewal (계획갱신)', () => {
  const template = getTaskTemplate('recipient-plan-renewal')!;

  it('has 3 steps in correct order', () => {
    expect(template.steps).toHaveLength(3);
    expect(template.steps.map((s) => s.name)).toEqual([
      '욕구-욕낙치',
      '지난계획평가',
      '새 계획서통보',
    ]);
  });
});

describe('recipient-new (신규수급자)', () => {
  const template = getTaskTemplate('recipient-new')!;

  it('has 수급자등록-고씨 as the first step', () => {
    expect(template.steps[0].name).toBe('수급자등록-고씨');
  });

  it('has 10 steps (수급자등록-고씨 + the 9 인정서갱신 steps)', () => {
    expect(template.steps).toHaveLength(10);
  });

  it('follows 인정서갱신 order after the first step', () => {
    const recognition = getTaskTemplate('recipient-recognition-renewal')!;
    const afterFirst = template.steps.slice(1).map((s) => s.name);
    expect(afterFirst).toEqual(recognition.steps.map((s) => s.name));
  });
});

describe('staff-new-preparation (신규직원입사자료준비)', () => {
  const template = getTaskTemplate('staff-new-preparation')!;

  it('has 7 steps in correct order', () => {
    expect(template.steps).toHaveLength(7);
    expect(template.steps.map((s) => s.name)).toEqual([
      '직원등록-고씨',
      '계약서',
      '서약서',
      '범죄경력조회',
      '건강검진',
      '신규직원교육확인',
      '희망이음 등록',
    ]);
  });
});

describe('staff-new-onboarding (신규직원업무)', () => {
  const template = getTaskTemplate('staff-new-onboarding')!;
  const preparation = getTaskTemplate('staff-new-preparation')!;

  it('includes all staff-new-preparation steps first', () => {
    const onboardingPrep = template.steps
      .slice(0, preparation.steps.length)
      .map((s) => s.name);
    expect(onboardingPrep).toEqual(preparation.steps.map((s) => s.name));
  });

  it('appends 입사신고 and 취득신고 after preparation steps', () => {
    const suffix = template.steps.slice(preparation.steps.length).map((s) => s.name);
    expect(suffix).toEqual(['입사신고', '취득신고']);
  });

  it('has 9 steps total', () => {
    expect(template.steps).toHaveLength(9);
  });
});

describe('staff-resignation (퇴사직원업무)', () => {
  const template = getTaskTemplate('staff-resignation')!;

  it('has 3 steps in correct order', () => {
    expect(template.steps).toHaveLength(3);
    expect(template.steps.map((s) => s.name)).toEqual([
      '퇴사신고',
      '상실신고',
      '퇴사처리-고씨',
    ]);
  });
});

describe('staff-recipient-termination (수급자종료)', () => {
  const template = getTaskTemplate('staff-recipient-termination')!;

  it('has 1 step', () => {
    expect(template.steps).toHaveLength(1);
    expect(template.steps[0].name).toBe('종료처리-고씨');
  });
});

describe('attachmentPolicy', () => {
  it('is "optional" on every step of every template', () => {
    for (const template of TASK_TEMPLATES) {
      for (const step of template.steps) {
        expect(step.attachmentPolicy).toBe('optional');
      }
    }
  });
});

describe('getTaskTemplate', () => {
  it('returns a template for a known id', () => {
    const t = getTaskTemplate('recipient-new');
    expect(t).toBeDefined();
    expect(t!.id).toBe('recipient-new');
  });

  it('returns undefined for an unknown id', () => {
    expect(getTaskTemplate('nonexistent')).toBeUndefined();
    expect(getTaskTemplate('')).toBeUndefined();
  });
});

describe('readonly contract', () => {
  it('TASK_TEMPLATES is a readonly array', () => {
    // TASK_TEMPLATES is typed as readonly TaskTemplate[]
    const arr: readonly TaskTemplate[] = TASK_TEMPLATES;
    expect(Array.isArray(arr)).toBe(true);
  });

  it('TaskTemplate.steps is a readonly array', () => {
    const t = getTaskTemplate('staff-resignation')!;
    const steps: readonly TaskStep[] = t.steps;
    expect(steps).toHaveLength(3);
  });

  it('individual step fields are readonly', () => {
    const t = getTaskTemplate('staff-recipient-termination')!;
    const step: TaskStep = t.steps[0];
    expect(step.name).toBe('종료처리-고씨');
    expect(step.attachmentPolicy).toBe('optional');
    // readonly compile-time: re-assignment of name / attachmentPolicy
    // would be a TS error; this test only validates shape.
  });
});

// ── 역할 계약 (allowedRoles / dedicatedRole) ──────────────────

const CENTER_MANAGER_ONLY_IDS = [
  'staff-new-onboarding',
  'staff-resignation',
  'staff-recipient-termination',
] as const;

const SOCIAL_WORKER_ELIGIBLE_IDS = [
  'recipient-recognition-renewal',
  'recipient-contract-renewal',
  'recipient-plan-renewal',
  'recipient-new',
  'staff-new-preparation',
] as const;

describe('allowedRoles', () => {
  it('every template includes center-manager', () => {
    for (const t of TASK_TEMPLATES) {
      expect(t.allowedRoles).toContain('center-manager');
    }
  });

  it('templates 1–5 include social-worker', () => {
    for (const id of SOCIAL_WORKER_ELIGIBLE_IDS) {
      const t = getTaskTemplate(id)!;
      expect(t.allowedRoles).toContain('social-worker');
    }
  });

  it('templates 6–8 allow center-manager only', () => {
    for (const id of CENTER_MANAGER_ONLY_IDS) {
      const t = getTaskTemplate(id)!;
      expect(t.allowedRoles).toEqual(['center-manager']);
    }
  });
});

describe('dedicatedRole', () => {
  it('is "center-manager" for templates 6–8', () => {
    for (const id of CENTER_MANAGER_ONLY_IDS) {
      const t = getTaskTemplate(id)!;
      expect(t.dedicatedRole).toBe('center-manager');
    }
  });

  it('is undefined for templates 1–5', () => {
    for (const id of SOCIAL_WORKER_ELIGIBLE_IDS) {
      const t = getTaskTemplate(id)!;
      expect(t.dedicatedRole).toBeUndefined();
    }
  });
});

describe('allowedRoles readonly contract', () => {
  it('allowedRoles is typed as readonly TaskRole[]', () => {
    const t = getTaskTemplate('recipient-new')!;
    const roles: readonly TaskRole[] = t.allowedRoles;
    expect(roles.length).toBeGreaterThanOrEqual(1);
  });

  it('dedicatedRole is typed as TaskRole | undefined', () => {
    const t = getTaskTemplate('staff-new-onboarding')!;
    const role: TaskRole | undefined = t.dedicatedRole;
    expect(role).toBe('center-manager');
  });
});

describe('roles do not alter existing step / attachment contracts', () => {
  it('step count and order are unchanged after role fields addition', () => {
    // spot-check a few templates to ensure existing structure is intact
    const r = getTaskTemplate('recipient-recognition-renewal')!;
    expect(r.steps).toHaveLength(9);
    expect(r.steps[0].name).toBe('인정서확보');
    expect(r.steps[0].attachmentPolicy).toBe('optional');
  });
});
