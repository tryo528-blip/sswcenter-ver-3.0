import './setup';
import { render, screen, fireEvent } from '@testing-library/react';
import { BrowserRouter } from 'react-router';
import { afterEach, describe, it, expect, vi } from 'vitest';
import Header from '../components/layout/Header';

describe('Header Component', () => {
  afterEach(() => vi.restoreAllMocks());

  it('renders top header structure with name, message, and clock', () => {
    render(
      <BrowserRouter>
        <Header user={{ display_name: '홍길동 관리자' }} />
      </BrowserRouter>,
    );

    expect(screen.getByTestId('app-header')).toBeInTheDocument();
    expect(screen.getByTestId('header-user-name')).toHaveTextContent('홍길동 관리자');
    expect(screen.getByTestId('header-center-message')).toHaveTextContent(
      '오늘도 어르신들의 건강하고 행복한 하루를 응원합니다.',
    );
    expect(screen.getByTestId('header-clock')).toBeInTheDocument();
    expect(screen.getByTestId('month-selector')).toBeInTheDocument();
  });

  it('renders monthly color selector with 12 options and updates color token', () => {
    const handleMonthChange = vi.fn();
    render(
      <BrowserRouter>
        <Header currentMonth={7} onMonthChange={handleMonthChange} />
      </BrowserRouter>,
    );

    const select = screen.getByLabelText('월별 강조색 선택') as HTMLSelectElement;
    expect(select).toBeInTheDocument();
    expect(select.options).toHaveLength(12);

    fireEvent.change(select, { target: { value: '3' } });
    expect(handleMonthChange).toHaveBeenCalledWith(3);
    expect(document.documentElement.dataset.themeMonth).toBe('3');
    expect(document.documentElement.style.getPropertyValue('--color-primary')).toBe('#059669');
  });
});
