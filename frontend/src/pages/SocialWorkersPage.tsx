import { useState } from 'react';
import { EditorialCard, EditorialPage } from '../components/common/EditorialPage';
import {
  SCHEDULE_TYPES,
  openSchedulePopup,
  type ScheduleKind,
} from '../components/schedule/schedulePopups';
import { useAuthSafe } from '../context/useAuth';

function currentMonthKey(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
}

export const SocialWorkersPage = () => {
  const { user } = useAuthSafe();
  const [month, setMonth] = useState(currentMonthKey);

  const openCalendar = (kind: ScheduleKind) => {
    openSchedulePopup(kind, month, kind === 'social-worker' ? user?.id : undefined);
  };

  return (
    <EditorialPage
      testId="page-social-workers"
      className="social-workers-page"
      title="사회복지사"
    >
      <EditorialCard title="달력형 일정표">
        <div className="social-worker-calendar-launcher">
          <label>
            조회 월
            <input
              type="month"
              aria-label="일정표 조회 월"
              value={month}
              onChange={(event) => setMonth(event.target.value || currentMonthKey())}
            />
          </label>
          <div className="social-worker-calendar-buttons">
            {SCHEDULE_TYPES.map((scheduleType) => (
              <button
                type="button"
                key={scheduleType.kind}
                onClick={() => openCalendar(scheduleType.kind)}
              >
                {scheduleType.label} 일정표 열기
              </button>
            ))}
          </div>
          <p>
            수급자·직원 일정표는 같은 일정 원장을 서로 다른 기준으로 표시합니다.
            개인 할 일은 본인의 사회복지사 일정표 안에서만 관리합니다.
          </p>
        </div>
      </EditorialCard>
    </EditorialPage>
  );
};

export default SocialWorkersPage;
