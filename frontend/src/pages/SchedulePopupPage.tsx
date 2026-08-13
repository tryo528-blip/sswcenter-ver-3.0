import { useEffect } from 'react';
import { useParams, useSearchParams } from 'react-router';
import { PersonalTodoPanel } from '../components/schedule/PersonalTodoPanel';
import { ScheduleLedger } from '../components/schedule/ScheduleLedger';
import { SCHEDULE_TYPES, type ScheduleKind } from '../components/schedule/schedulePopups';
import { useAuthSafe } from '../context/useAuth';
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

export const SchedulePopupPage = () => {
  const { user } = useAuthSafe();
  const { scheduleKind } = useParams<{ scheduleKind: ScheduleKind }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const monthKey = normalizedMonth(searchParams.get('month'));
  const scheduleType = SCHEDULE_TYPES.find((item) => item.kind === scheduleKind);
  const monthNumber = Number(monthKey.slice(5, 7));
  const showPersonalTodos = scheduleKind === 'social-worker' && user?.role_code !== 'ADMIN';

  useEffect(() => {
    const token = getMonthlyColorToken(monthNumber);
    document.documentElement.style.setProperty('--color-primary', token.hex);
    document.documentElement.dataset.themeMonth = String(monthNumber);
  }, [monthNumber]);

  if (!scheduleType || !scheduleKind) {
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
        <button type="button" onClick={() => window.close()} aria-label="일정표 닫기">닫기</button>
      </header>

      <div className="schedule-popup-toolbar">
        <button type="button" onClick={() => changeMonth(-1)} aria-label="이전 달">←</button>
        <strong>{monthKey.replace('-', '년 ')}월</strong>
        <button type="button" onClick={() => changeMonth(1)} aria-label="다음 달">→</button>
      </div>

      <div className={`schedule-popup-layout${showPersonalTodos ? ' has-personal-todos' : ''}`}>
        <ScheduleLedger kind={scheduleKind} month={monthKey} />
        {showPersonalTodos && <PersonalTodoPanel />}
      </div>
    </main>
  );
};

export default SchedulePopupPage;
