/**
 * 정적 업무 템플릿 계약
 *
 * 임무카드가 나중에 사용할 읽기 전용 타입/상수/조회 함수만 제공한다.
 * 실제 업무 생성, 저장, 권한 판정, 담당자 연결은 이 slice에서 하지 않는다.
 */

/** 개별 업무 단계 */
export interface TaskStep {
  readonly name: string;
  /** 이미지·파일 첨부가 없는 상태도 정상 완료 가능 */
  readonly attachmentPolicy: 'optional';
}

/** 템플릿을 수행할 수 있는 역할 */
export type TaskRole = 'social-worker' | 'center-manager';

/** 정적 업무 템플릿 */
export interface TaskTemplate {
  readonly id: string;
  readonly title: string;
  readonly steps: readonly TaskStep[];
  /** 이 템플릿을 수행할 수 있는 역할 목록 */
  readonly allowedRoles: readonly TaskRole[];
  /** 센터장 전담 업무일 경우 명시 (1~5번 템플릿에는 설정하지 않음) */
  readonly dedicatedRole?: TaskRole;
}

function step(name: string): TaskStep {
  return { name, attachmentPolicy: 'optional' };
}

// ── 수급자 템플릿 ──────────────────────────────────────────────

const RECOGNITION_RENEWAL_STEPS: readonly TaskStep[] = [
  step('인정서확보'),
  step('계약서작성'),
  step('계약- 공단등록'),
  step('계약- 고씨등록'),
  step('욕구-욕낙치'),
  step('지난계획평가'),
  step('새 계획서 통보'),
  step('일정등록-공단'),
  step('일정등록-고씨'),
];

const CONTRACT_RENEWAL_STEPS: readonly TaskStep[] = [
  step('계약서작성'),
  step('계약- 공단등록'),
  step('계약- 고씨등록'),
  step('욕구-욕낙치'),
  step('지난계획평가'),
  step('새 계획서 통보'),
  step('일정등록-공단'),
  step('일정등록-고씨'),
];

// ── 직원 템플릿 ────────────────────────────────────────────────

const STAFF_NEW_PREPARATION_STEPS: readonly TaskStep[] = [
  step('직원등록-고씨'),
  step('계약서'),
  step('서약서'),
  step('범죄경력조회'),
  step('건강검진'),
  step('신규직원교육확인'),
  step('희망이음 등록'),
];

// ── 템플릿 목록 ────────────────────────────────────────────────

export const TASK_TEMPLATES: readonly TaskTemplate[] = [
  {
    id: 'recipient-recognition-renewal',
    title: '인정서갱신',
    steps: RECOGNITION_RENEWAL_STEPS,
    allowedRoles: ['social-worker', 'center-manager'],
  },
  {
    id: 'recipient-contract-renewal',
    title: '계약갱신',
    steps: CONTRACT_RENEWAL_STEPS,
    allowedRoles: ['social-worker', 'center-manager'],
  },
  {
    id: 'recipient-plan-renewal',
    title: '계획갱신',
    steps: [step('욕구-욕낙치'), step('지난계획평가'), step('새 계획서통보')],
    allowedRoles: ['social-worker', 'center-manager'],
  },
  {
    id: 'recipient-new',
    title: '신규수급자',
    steps: [step('수급자등록-고씨'), ...RECOGNITION_RENEWAL_STEPS],
    allowedRoles: ['social-worker', 'center-manager'],
  },
  {
    id: 'staff-new-preparation',
    title: '신규직원입사자료준비',
    steps: STAFF_NEW_PREPARATION_STEPS,
    allowedRoles: ['social-worker', 'center-manager'],
  },
  {
    id: 'staff-new-onboarding',
    title: '신규직원업무',
    steps: [
      ...STAFF_NEW_PREPARATION_STEPS,
      step('입사신고'),
      step('취득신고'),
    ],
    allowedRoles: ['center-manager'],
    dedicatedRole: 'center-manager',
  },
  {
    id: 'staff-resignation',
    title: '퇴사직원업무',
    steps: [step('퇴사신고'), step('상실신고'), step('퇴사처리-고씨')],
    allowedRoles: ['center-manager'],
    dedicatedRole: 'center-manager',
  },
  {
    id: 'staff-recipient-termination',
    title: '수급자종료',
    steps: [step('종료처리-고씨')],
    allowedRoles: ['center-manager'],
    dedicatedRole: 'center-manager',
  },
];

export function getTaskTemplate(id: string): TaskTemplate | undefined {
  return TASK_TEMPLATES.find((t) => t.id === id);
}
