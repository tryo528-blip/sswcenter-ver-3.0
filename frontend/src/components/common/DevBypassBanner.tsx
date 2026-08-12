import React from 'react';

export interface DevBypassBannerProps {
  enabled?: boolean;
}

export const DevBypassBanner: React.FC<DevBypassBannerProps> = ({ enabled }) => {
  if (!import.meta.env.DEV) {
    return null;
  }

  const bypassEnabled =
    enabled ?? import.meta.env.VITE_DEV_LOGIN_BYPASS === 'true';

  if (!bypassEnabled) {
    return null;
  }

  return (
    <div
      className="dev-bypass-banner"
      data-testid="dev-bypass-banner"
      data-bypass-enabled={bypassEnabled}
    >
      <div>
        <span className="dev-bypass-tag">개발 모드</span>
        <span>로그인 우회: 사용 중 · 합성 개발 DB 전용</span>
      </div>
      <div style={{ fontSize: '11px', opacity: 0.8 }}>
        운영 빌드에서는 개발 우회 기능과 표시가 제거됩니다.
      </div>
    </div>
  );
};

export default DevBypassBanner;
