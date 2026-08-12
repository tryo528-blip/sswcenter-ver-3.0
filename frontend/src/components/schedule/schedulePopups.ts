export const SCHEDULE_TYPES = [
  { kind: 'recipient', label: '수급자' },
  { kind: 'care-worker', label: '요양보호사' },
  { kind: 'social-worker', label: '사회복지사' },
] as const;

export type ScheduleKind = (typeof SCHEDULE_TYPES)[number]['kind'];

export function schedulePopupTarget(kind: ScheduleKind): string {
  return `sswcenter-schedule-${kind}`;
}

export function openSchedulePopup(kind: ScheduleKind, month: string): Window | null {
  const params = new URLSearchParams({ month });
  const popup = window.open(
    `/schedules/${kind}?${params.toString()}`,
    schedulePopupTarget(kind),
    'popup=yes,width=1280,height=900,resizable=yes,scrollbars=yes',
  );
  popup?.focus();
  return popup;
}
