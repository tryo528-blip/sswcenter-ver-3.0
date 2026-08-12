import './setup';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import LoadingStatus from '../components/status/LoadingStatus';
import ErrorStatus from '../components/status/ErrorStatus';
import SaveStatus from '../components/status/SaveStatus';

describe('Common Status Components', () => {
  describe('LoadingStatus', () => {
    it('renders default Korean loading message and spinner', () => {
      render(<LoadingStatus />);
      const el = screen.getByTestId('loading-status');
      expect(el).toBeInTheDocument();
      expect(el).toHaveTextContent('데이터를 불러오는 중입니다...');
    });

    it('renders custom loading message', () => {
      render(<LoadingStatus message="직원 목록을 조회 중입니다..." />);
      expect(screen.getByTestId('loading-status')).toHaveTextContent('직원 목록을 조회 중입니다...');
    });
  });

  describe('ErrorStatus', () => {
    it('renders error title and message', () => {
      render(<ErrorStatus title="연동 실패" message="데이터베이스 접속 오류입니다." />);
      const el = screen.getByTestId('error-status');
      expect(el).toBeInTheDocument();
      expect(el).toHaveTextContent('연동 실패');
      expect(el).toHaveTextContent('데이터베이스 접속 오류입니다.');
    });

    it('calls onRetry callback when retry button is clicked', () => {
      const handleRetry = vi.fn();
      render(<ErrorStatus onRetry={handleRetry} />);
      const btn = screen.getByRole('button', { name: '다시 시도' });
      fireEvent.click(btn);
      expect(handleRetry).toHaveBeenCalledTimes(1);
    });
  });

  describe('SaveStatus', () => {
    it('returns null when status is idle', () => {
      const { container } = render(<SaveStatus status="idle" />);
      expect(container.firstChild).toBeNull();
    });

    it('renders saving state', () => {
      render(<SaveStatus status="saving" />);
      const el = screen.getByTestId('save-status');
      expect(el).toHaveTextContent('저장 중...');
    });

    it('renders saved state with optional timestamp', () => {
      render(<SaveStatus status="saved" lastSavedAt="19:57:00" />);
      const el = screen.getByTestId('save-status');
      expect(el).toHaveTextContent('저장 완료 (19:57:00)');
    });

    it('renders error state with error message', () => {
      render(<SaveStatus status="error" errorMessage="네트워크 접속 불안정" />);
      const el = screen.getByTestId('save-status');
      expect(el).toHaveTextContent('저장 실패 : 네트워크 접속 불안정');
    });
  });
});
