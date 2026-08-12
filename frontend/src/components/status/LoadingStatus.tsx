import React from 'react';

export interface LoadingStatusProps {
  message?: string;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

export const LoadingStatus: React.FC<LoadingStatusProps> = ({
  message = '데이터를 불러오는 중입니다...',
  size = 'md',
  className = '',
}) => {
  return (
    <div
      className={`status-container status-loading size-${size} ${className}`}
      role="status"
      aria-live="polite"
      data-testid="loading-status"
    >
      <span className="status-spinner" aria-hidden="true" />
      <span>{message}</span>
    </div>
  );
};

export default LoadingStatus;
