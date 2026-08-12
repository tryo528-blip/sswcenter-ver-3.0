import { describe, expect, it } from 'vitest';
import { evaluateContinuingEducation } from '../components/staff/continuingEducation';

describe('continuing education eligibility', () => {
  it('matches the target year to the birth-year parity', () => {
    expect(
      evaluateContinuingEducation({
        birthDate: '1971-04-03',
        careWorkerIssuedDate: '2019-06-01',
        isWorkingCareWorker: true,
        targetYear: 2025,
      }).status,
    ).toBe('DUE');
    expect(
      evaluateContinuingEducation({
        birthDate: '1971-04-03',
        careWorkerIssuedDate: '2019-06-01',
        isWorkingCareWorker: true,
        targetYear: 2026,
      }).status,
    ).toBe('NOT_DUE');
  });

  it('exempts through the end of the year in which two years have elapsed', () => {
    expect(
      evaluateContinuingEducation({
        birthDate: '1971-04-03',
        careWorkerIssuedDate: '2023-02-10',
        isWorkingCareWorker: true,
        targetYear: 2025,
      }).status,
    ).toBe('EXEMPT');
    expect(
      evaluateContinuingEducation({
        birthDate: '1971-04-03',
        careWorkerIssuedDate: '2022-02-10',
        isWorkingCareWorker: true,
        targetYear: 2025,
      }).status,
    ).toBe('DUE');
  });

  it('applies the acquisition-year boundary in the 2026 even-year cycle', () => {
    expect(
      evaluateContinuingEducation({
        birthDate: '1970-04-03',
        careWorkerIssuedDate: '2023-12-31',
        isWorkingCareWorker: true,
        targetYear: 2026,
      }).status,
    ).toBe('DUE');
    expect(
      evaluateContinuingEducation({
        birthDate: '1970-04-03',
        careWorkerIssuedDate: '2024-01-01',
        isWorkingCareWorker: true,
        targetYear: 2026,
      }).status,
    ).toBe('EXEMPT');
  });

  it('does not apply when the employee is not currently working as a care worker', () => {
    expect(
      evaluateContinuingEducation({
        birthDate: '1971-04-03',
        careWorkerIssuedDate: '2019-06-01',
        isWorkingCareWorker: false,
        targetYear: 2025,
      }).status,
    ).toBe('NOT_APPLICABLE');
  });

  it('requires review when a current care worker has no qualification date', () => {
    expect(
      evaluateContinuingEducation({
        birthDate: '1971-04-03',
        careWorkerIssuedDate: null,
        isWorkingCareWorker: true,
        targetYear: 2025,
      }).status,
    ).toBe('NEEDS_REVIEW');
  });
});
