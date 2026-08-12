export type ContinuingEducationStatus =
  | 'DUE'
  | 'EXEMPT'
  | 'NOT_DUE'
  | 'NOT_APPLICABLE'
  | 'NOT_QUALIFIED_YET'
  | 'NEEDS_REVIEW';

export type ContinuingEducationEvaluation = {
  status: ContinuingEducationStatus;
  targetYear: number;
};

function isoYear(value: string | null | undefined): number | null {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const year = Number(value.slice(0, 4));
  return Number.isSafeInteger(year) ? year : null;
}

export function evaluateContinuingEducation({
  birthDate,
  careWorkerIssuedDate,
  isWorkingCareWorker,
  targetYear,
}: {
  birthDate: string | null | undefined;
  careWorkerIssuedDate: string | null | undefined;
  isWorkingCareWorker: boolean;
  targetYear: number;
}): ContinuingEducationEvaluation {
  const birthYear = isoYear(birthDate);
  const issuedYear = isoYear(careWorkerIssuedDate);

  if (!Number.isSafeInteger(targetYear) || birthYear === null) {
    return { status: 'NEEDS_REVIEW', targetYear };
  }
  if (!isWorkingCareWorker) {
    return { status: 'NOT_APPLICABLE', targetYear };
  }
  if (issuedYear === null) {
    return { status: 'NEEDS_REVIEW', targetYear };
  }
  if (issuedYear > targetYear) {
    return { status: 'NOT_QUALIFIED_YET', targetYear };
  }
  if (birthYear % 2 !== targetYear % 2) {
    return { status: 'NOT_DUE', targetYear };
  }
  if (targetYear - issuedYear <= 2) {
    return { status: 'EXEMPT', targetYear };
  }
  return { status: 'DUE', targetYear };
}
