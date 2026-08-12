/**
 * Design Tokens & Monthly Color Definitions for SSWCenter 2.0
 */

export interface MonthlyColorToken {
  month: number; // 1 ~ 12
  name: string; // e.g. "1월 (Royal Blue)"
  hex: string;
  accentHex?: string;
  cssVariable: string;
}

export const MONTHLY_COLOR_TOKENS: Record<number, MonthlyColorToken> = {
  1: { month: 1, name: '1월 (Royal Blue)', hex: '#2563eb', accentHex: '#0f766e', cssVariable: '--color-primary-01' },
  2: { month: 2, name: '2월 (Violet)', hex: '#7c3aed', accentHex: '#d97706', cssVariable: '--color-primary-02' },
  3: { month: 3, name: '3월 (Spring Emerald)', hex: '#059669', accentHex: '#f97316', cssVariable: '--color-primary-03' },
  4: { month: 4, name: '4월 (Cherry Pink)', hex: '#db2777', accentHex: '#4338ca', cssVariable: '--color-primary-04' },
  5: { month: 5, name: '5월 (Fresh Teal)', hex: '#0d9488', accentHex: '#ea580c', cssVariable: '--color-primary-05' },
  6: { month: 6, name: '6월 (Sky Blue)', hex: '#0284c7', accentHex: '#b45309', cssVariable: '--color-primary-06' },
  7: { month: 7, name: '7월 (Deep Ocean)', hex: '#0f766e', accentHex: '#e11d48', cssVariable: '--color-primary-07' },
  8: { month: 8, name: '8월 (Midnight Navy)', hex: '#1e40af', accentHex: '#f59e0b', cssVariable: '--color-primary-08' },
  9: { month: 9, name: '9월 (Autumn Amber)', hex: '#d97706', accentHex: '#166534', cssVariable: '--color-primary-09' },
  10: { month: 10, name: '10월 (Pumpkin Orange)', hex: '#ea580c', accentHex: '#1d4ed8', cssVariable: '--color-primary-10' },
  11: { month: 11, name: '11월 (Warm Chestnut)', hex: '#78350f', accentHex: '#ca8a04', cssVariable: '--color-primary-11' },
  12: {
    month: 12,
    name: '12월 (Christmas Holly)',
    hex: '#15803d',
    accentHex: '#b42318',
    cssVariable: '--color-primary-12',
  },
};

/**
 * Get monthly color token by month number (1-12)
 */
export function getMonthlyColorToken(month: number): MonthlyColorToken {
  const normalizedMonth = Math.max(1, Math.min(12, Math.floor(month)));
  return MONTHLY_COLOR_TOKENS[normalizedMonth] || MONTHLY_COLOR_TOKENS[7];
}

/**
 * Canonical 8 Sidebar items in exact specification order
 */
export interface SidebarMenuItem {
  id: string;
  order: number;
  label: string;
  path: string;
  description: string;
}

export const CANONICAL_SIDEBAR_ITEMS: readonly SidebarMenuItem[] = [
  { id: 'dashboard', order: 1, label: '대시보드', path: '/dashboard', description: '업무카드, 개인할일, 기한마감 현황' },
  { id: 'recipients', order: 2, label: '수급자', path: '/recipients', description: '수급자 목록, 계약, 인정등급' },
  { id: 'staff', order: 3, label: '직원', path: '/staff', description: '직원 목록, 교육, 상담, 자격' },
  { id: 'social-workers', order: 4, label: '사회복지사', path: '/social-workers', description: '연차휴가, 담당배정, 월방문관리' },
  { id: 'copay', order: 5, label: '본인부담금', path: '/copay', description: '청구, 수납, 명세서, 본인부담금 월확정' },
  { id: 'io', order: 6, label: '입출력', path: '/io', description: '자료수집, RFID/실제근무 검토, OCR대기' },
  { id: 'filebox', order: 7, label: '파일함', path: '/filebox', description: '탐색기형 문서창고, 정규서류, OCR' },
  { id: 'settings', order: 8, label: '설정', path: '/settings', description: '공휴일, 상단메시지, 계정관리, 감사로그 (관리자 전용)' },
] as const;
