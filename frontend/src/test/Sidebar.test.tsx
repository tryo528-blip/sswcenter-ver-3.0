import './setup';
import { render, screen } from '@testing-library/react';
import { BrowserRouter } from 'react-router';
import { describe, it, expect } from 'vitest';
import Sidebar from '../components/layout/Sidebar';
import { CANONICAL_SIDEBAR_ITEMS } from '../design-system/tokens';

describe('Sidebar Component', () => {
  it('renders the sidebar element', () => {
    render(
      <BrowserRouter>
        <Sidebar />
      </BrowserRouter>
    );
    expect(screen.getByTestId('app-sidebar')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Good Office Companion' })).toHaveTextContent(
      'Good OfficeCompanion',
    );
    expect(screen.queryByText('고씨(GOC)')).not.toBeInTheDocument();
  });

  it('renders exactly 8 canonical sidebar items in correct order', () => {
    render(
      <BrowserRouter>
        <Sidebar />
      </BrowserRouter>
    );

    const items = screen.getAllByRole('menuitem');
    expect(items).toHaveLength(8);

    const expectedLabels = [
      '대시보드',
      '수급자',
      '직원',
      '사회복지사',
      '본인부담금',
      '입출력',
      '파일함',
      '설정',
    ];

    expectedLabels.forEach((label, index) => {
      expect(items[index]).toHaveTextContent(label);
      expect(CANONICAL_SIDEBAR_ITEMS[index].order).toBe(index + 1);
    });
  });

  it('links to correct canonical route paths', () => {
    render(
      <BrowserRouter>
        <Sidebar />
      </BrowserRouter>
    );

    expect(screen.getByTestId('sidebar-item-dashboard')).toHaveAttribute('href', '/dashboard');
    expect(screen.getByTestId('sidebar-item-recipients')).toHaveAttribute('href', '/recipients');
    expect(screen.getByTestId('sidebar-item-staff')).toHaveAttribute('href', '/staff');
    expect(screen.getByTestId('sidebar-item-social-workers')).toHaveAttribute('href', '/social-workers');
    expect(screen.getByTestId('sidebar-item-copay')).toHaveAttribute('href', '/copay');
    expect(screen.getByTestId('sidebar-item-io')).toHaveAttribute('href', '/io');
    expect(screen.getByTestId('sidebar-item-filebox')).toHaveAttribute('href', '/filebox');
    expect(screen.getByTestId('sidebar-item-settings')).toHaveAttribute('href', '/settings');
  });
});
