import React from 'react';

export type SaveState = 'idle' | 'saving' | 'saved' | 'error';

export interface SaveStatusProps {
  status: SaveState;
  lastSavedAt?: Date | string;
  errorMessage?: string;
  className?: string;
}

export const SaveStatus: React.FC<SaveStatusProps> = ({
  status,
  lastSavedAt,
  errorMessage,
  className = '',
}) => {
  if (status === 'idle') {
    return null;
  }

  const formattedTime = lastSavedAt
    ? typeof lastSavedAt === 'string'
      ? lastSavedAt
      : lastSavedAt.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    : '';

  return (
    <div
      className={`status-save status-save-${status} ${className}`}
      data-testid="save-status"
      data-status={status}
    >
      {status === 'saving' && (
        <>
          <span className="status-spinner" aria-hidden="true" style={{ width: '10px', height: '10px' }} />
          <span>저장 중...</span>
        </>
      )}

      {status === 'saved' && (
        <>
          <span aria-hidden="true">✓</span>
          <span>저장 완료 {formattedTime && `(${formattedTime})`}</span>
        </>
      )}

      {status === 'error' && (
        <>
          <span aria-hidden="true">⚠</span>
          <span>저장 실패 {errorMessage ? `: ${errorMessage}` : ''}</span>
        </>
      )}
    </div>
  );
};

export default SaveStatus;
