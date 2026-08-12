import { describe, it, expect } from 'vitest';
import {
  MONTHLY_COLOR_TOKENS,
  getMonthlyColorToken,
  CANONICAL_SIDEBAR_ITEMS,
} from '../design-system/tokens';

describe('Design Tokens & Monthly Color Contract', () => {
  it('defines 12 monthly color tokens with valid hex values and CSS variable names', () => {
    for (let month = 1; month <= 12; month++) {
      const token = MONTHLY_COLOR_TOKENS[month];
      expect(token).toBeDefined();
      expect(token.month).toBe(month);
      expect(token.hex).toMatch(/^#[0-9a-fA-F]{6}$/);
      expect(token.cssVariable).toBe(`--color-primary-${String(month).padStart(2, '0')}`);
    }
  });

  it('getMonthlyColorToken returns correct token and falls back safely', () => {
    expect(getMonthlyColorToken(1).hex).toBe('#2563eb');
    expect(getMonthlyColorToken(7).hex).toBe('#0f766e');
    expect(getMonthlyColorToken(12).hex).toBe('#15803d');
    // Out of bounds fallback
    expect(getMonthlyColorToken(0).hex).toBe('#2563eb'); // clamped to 1
    expect(getMonthlyColorToken(15).hex).toBe('#15803d'); // clamped to 12
  });

  it('verifies 8 canonical sidebar items structure and sequential order 1..8', () => {
    expect(CANONICAL_SIDEBAR_ITEMS).toHaveLength(8);

    CANONICAL_SIDEBAR_ITEMS.forEach((item, idx) => {
      expect(item.order).toBe(idx + 1);
      expect(item.id).toBeTruthy();
      expect(item.label).toBeTruthy();
      expect(item.path.startsWith('/')).toBe(true);
    });
  });
});
