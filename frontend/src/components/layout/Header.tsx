import React, { useEffect, useState } from 'react';
import { useLocation } from 'react-router';
import { getMonthlyColorToken } from '../../design-system/tokens';
import { useAuthSafe } from '../../context/useAuth';

export interface HeaderProps {
  currentMonth?: number;
  onMonthChange?: (month: number) => void;
  user?: { display_name: string } | null;
}

const TRANSPARENT_HEADER_PATH_PREFIXES = ['/staff', '/social-workers', '/copay'] as const;

export const Header: React.FC<HeaderProps> = ({
  currentMonth = new Date().getMonth() + 1,
  onMonthChange,
  user: userProp,
}) => {
  const auth = useAuthSafe();
  const location = useLocation();
  const isTransparentHeader = TRANSPARENT_HEADER_PATH_PREFIXES.some((prefix) =>
    location.pathname.startsWith(prefix),
  );

  const currentUser = userProp !== undefined ? userProp : auth.user;
  const authError = auth.error;

  const [now, setNow] = useState<Date>(new Date());
  const [selectedMonth, setSelectedMonth] = useState<number>(currentMonth);

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    const token = getMonthlyColorToken(selectedMonth);
    document.documentElement.style.setProperty('--color-primary', token.hex);
    document.documentElement.style.setProperty('--color-seasonal-accent', token.accentHex ?? token.hex);
    document.documentElement.dataset.themeMonth = String(selectedMonth);
  }, [selectedMonth]);

  const handleMonthSelect = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const m = parseInt(e.target.value, 10);
    setSelectedMonth(m);
    if (onMonthChange) {
      onMonthChange(m);
    }
  };

  const dateStr = now.toLocaleDateString('ko-KR', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    weekday: 'short',
  });
  const timeStr = now.toLocaleTimeString('ko-KR', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });

  return (
    <header
      className={`app-header${isTransparentHeader ? ' app-header-transparent' : ''}`}
      data-testid="app-header"
    >
      <div className="header-left">
        {currentUser && (
          <span className="header-user-name" data-testid="header-user-name">
            {currentUser.display_name}
          </span>
        )}
        <div className="header-message" data-testid="header-center-message">
          <span className="header-message-text">오늘도 어르신들의 건강하고 행복한 하루를 응원합니다.</span>
        </div>
      </div>

      <div className="header-right">
        <div className="month-selector-widget" data-testid="month-selector">
          <label className="visually-hidden" htmlFor="month-select">
            월별 강조색 선택
          </label>
          <select
            id="month-select"
            className="month-selector-select"
            value={selectedMonth}
            onChange={handleMonthSelect}
            aria-label="월별 강조색 선택"
          >
            {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => {
              const tok = getMonthlyColorToken(m);
              return (
                <option key={m} value={m}>
                  {tok.month}월
                </option>
              );
            })}
          </select>
        </div>

        <div className="header-clock-container" data-testid="header-clock">
          <span>{dateStr}</span>
          <span className="header-clock-time">{timeStr}</span>
        </div>
        {authError && (
          <span className="header-auth-error" role="status">
            {authError}
          </span>
        )}
      </div>
    </header>
  );
};

export default Header;
