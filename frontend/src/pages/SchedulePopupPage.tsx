import { useEffect, useMemo } from 'react';
import { useParams, useSearchParams } from 'react-router';
import { SCHEDULE_TYPES, type ScheduleKind } from '../components/schedule/schedulePopups';
import { getMonthlyColorToken } from '../design-system/tokens';

function currentMonthKey(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
}

function normalizedMonth(value: string | null): string {
  if (!value || !/^\d{4}-(0[1-9]|1[0-2])$/.test(value)) return currentMonthKey();
  return value;
}

function moveMonth(monthKey: string, offset: number): string {
  const [year, month] = monthKey.split('-').map(Number);
  const moved = new Date(year, month - 1 + offset, 1);
  return `${moved.getFullYear()}-${String(moved.getMonth() + 1).padStart(2, '0')}`;
}

function monthCells(monthKey: string): Array<number | null> {
  const [year, month] = monthKey.split('-').map(Number);
  const firstDay = new Date(year, month - 1, 1).getDay();
  const lastDate = new Date(year, month, 0).getDate();
  const cells: Array<number | null> = Array.from({ length: firstDay }, () => null);
  for (let day = 1; day <= lastDate; day += 1) cells.push(day);
  while (cells.length % 7 !== 0) cells.push(null);
  return cells;
}

export const SchedulePopupPage = () => {
  const { scheduleKind } = useParams<{ scheduleKind: ScheduleKind }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const monthKey = normalizedMonth(searchParams.get('month'));
  const scheduleType = SCHEDULE_TYPES.find((item) => item.kind === scheduleKind);
  const cells = useMemo(() => monthCells(monthKey), [monthKey]);
  const monthNumber = Number(monthKey.slice(5, 7));

  useEffect(() => {
    const token = getMonthlyColorToken(monthNumber);
    document.documentElement.style.setProperty('--color-primary', token.hex);
    document.documentElement.dataset.themeMonth = String(monthNumber);
  }, [monthNumber]);

  if (!scheduleType) {
    return <main className="schedule-popup-page">일정표 종류를 확인해주세요.</main>;
  }

  const changeMonth = (offset: number) => {
    setSearchParams({ month: moveMonth(monthKey, offset) }, { replace: true });
  };

  return (
    <main className="schedule-popup-page" data-testid={`schedule-popup-${scheduleType.kind}`}>
      <header className="schedule-popup-header">
        <div>
          <span>{scheduleType.label}</span>
          <h1>월간 일정표</h1>
        </div>
        <button type="button" onClick={() => window.close()} aria-label="일정표 닫기">
          닫기
        </button>
      </header>

      <div className="schedule-popup-toolbar">
        <button type="button" onClick={() => changeMonth(-1)} aria-label="이전 달">
          ←
        </button>
        <strong>{monthKey.replace('-', '년 ')}월</strong>
        <button type="button" onClick={() => changeMonth(1)} aria-label="다음 달">
          →
        </button>
      </div>

      <section className="schedule-calendar" aria-label={`${scheduleType.label} ${monthKey} 일정`}>
        <div className="schedule-weekdays" aria-hidden="true">
          {['일', '월', '화', '수', '목', '금', '토'].map((day) => <span key={day}>{day}</span>)}
        </div>
        <div className="schedule-calendar-grid">
          {cells.map((day, index) => (
            <div className={day === null ? 'is-empty' : ''} key={`${monthKey}-${index}`}>
              {day === null ? null : <span>{day}</span>}
            </div>
          ))}
        </div>
      </section>
      <p className="schedule-popup-empty">등록된 일정이 없습니다.</p>
    </main>
  );
};

export default SchedulePopupPage;
