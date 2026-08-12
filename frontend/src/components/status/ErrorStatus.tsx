import React from 'react';

export interface ErrorStatusProps {
  title?: string;
  message?: string;
  onRetry?: () => void;
  className?: string;
}

export const ErrorStatus: React.FC<ErrorStatusProps> = ({
  title = '오류가 발생했습니다',
  message = '요청을 처리하는 도중 문제가 발생했습니다. 잠시 후 다시 시도해 주세요.',
  onRetry,
  className = '',
}) => {
  return (
    <div
      className={`status-container status-error ${className}`}
      role="alert"
      data-testid="error-status"
    >
      <div>
        <strong>{title}</strong>
        {message && <div style={{ fontSize: '12px', marginTop: '4px' }}>{message}</div>}
      </div>
      {onRetry && (
        <button
          type="button"
          className="header-btn"
          onClick={onRetry}
          style={{ marginLeft: '12px', padding: '4px 10px', fontSize: '12px' }}
        >
          다시 시도
        </button>
      )}
    </div>
  );
};

export default ErrorStatus;
