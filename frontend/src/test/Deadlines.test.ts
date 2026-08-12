import { describe, it, expect } from 'vitest';
import { computeDday } from '../components/dashboard/deadlines';

describe('computeDday', () => {
  // --- Future: at least 3 days ---
  it('returns D-3 for a deadline 3 days ahead', () => {
    const result = computeDday('2026-08-03', '2026-08-06');
    expect(result).toEqual({ dday: 'D-3', actualDate: '8/6' });
  });

  it('returns D-6 for a deadline 6 days ahead', () => {
    const result = computeDday('2026-08-03', '2026-08-09');
    expect(result).toEqual({ dday: 'D-6', actualDate: '8/9' });
  });

  it('returns D-13 for a deadline 13 days ahead', () => {
    const result = computeDday('2026-08-03', '2026-08-16');
    expect(result).toEqual({ dday: 'D-13', actualDate: '8/16' });
  });

  // --- Today ---
  it('returns D-DAY when the deadline is today', () => {
    const result = computeDday('2026-08-03', '2026-08-03');
    expect(result).toEqual({ dday: 'D-DAY', actualDate: '8/3' });
  });

  // --- Past: at least 2 days ---
  it('returns D+7 for a deadline 7 days ago', () => {
    const result = computeDday('2026-08-10', '2026-08-03');
    expect(result).toEqual({ dday: 'D+7', actualDate: '8/3' });
  });

  it('returns D+6 for a deadline 6 days ago', () => {
    const result = computeDday('2026-08-03', '2026-07-28');
    expect(result).toEqual({ dday: 'D+6', actualDate: '7/28' });
  });

  // --- actualDate: M/D without year or zero-padding ---
  it('formats actualDate as M/D without year or zero-padding', () => {
    const jan = computeDday('2026-01-01', '2026-12-31');
    expect(jan.actualDate).toBe('12/31');

    const feb = computeDday('2026-12-01', '2027-02-05');
    expect(feb.actualDate).toBe('2/5');
  });

  // --- Boundary: month / year edges ---
  it('handles month boundary correctly', () => {
    const result = computeDday('2026-08-31', '2026-09-01');
    expect(result).toEqual({ dday: 'D-1', actualDate: '9/1' });
  });

  it('handles year boundary correctly', () => {
    const result = computeDday('2026-12-31', '2027-01-01');
    expect(result).toEqual({ dday: 'D-1', actualDate: '1/1' });
  });

  it('computes past across a year boundary', () => {
    const result = computeDday('2027-01-01', '2026-12-25');
    expect(result).toEqual({ dday: 'D+7', actualDate: '12/25' });
  });

  // --- Date object inputs ---
  it('accepts Date objects and normalises to local midnight', () => {
    const today = new Date(2026, 7, 3, 14, 30, 0); // Aug 3, 2026 14:30 local
    const deadline = new Date(2026, 7, 6, 9, 0, 0); // Aug 6, 2026 09:00 local
    const result = computeDday(today, deadline);
    expect(result).toEqual({ dday: 'D-3', actualDate: '8/6' });
  });

  // --- Invalid / bad date inputs ---
  it('throws when today is an unparseable string', () => {
    expect(() => computeDday('not-a-date', '2026-08-03')).toThrow('Invalid date');
  });

  it('throws when deadline is an empty string', () => {
    expect(() => computeDday('2026-08-03', '')).toThrow('Invalid date');
  });

  it('throws when a Date object is invalid (NaN)', () => {
    expect(() => computeDday(new Date('invalid'), '2026-08-03')).toThrow('Invalid date');
  });

  it('throws when both arguments are invalid', () => {
    expect(() => computeDday('', '')).toThrow('Invalid date');
  });

  it('throws for non-existent calendar date 2026-13-99', () => {
    expect(() => computeDday('2026-13-99', '2026-08-03')).toThrow(/Invalid date/);
  });

  it('throws for non-existent calendar date 2026-02-30', () => {
    expect(() => computeDday('2026-02-30', '2026-08-03')).toThrow(/Invalid date/);
  });
});
