import React from 'react';
import { Outlet, useLocation } from 'react-router';
import Sidebar from './Sidebar';
import Header from './Header';

export const AppLayout: React.FC = () => {
  const location = useLocation();
  const isDashboard = location.pathname.startsWith('/dashboard');
  const isRecipients = location.pathname.startsWith('/recipients');
  const shellClass = isDashboard ? 'app-shell app-shell-dashboard' : 'app-shell';
  const contentClass = `app-content${isRecipients ? ' app-content-recipients' : ''}`;

  return (
    <div className={shellClass} data-testid="app-shell">
      <Sidebar />
      <div className="app-main-viewport">
        <Header />
        <main className={contentClass} data-testid="app-content">
          <Outlet />
        </main>
      </div>
    </div>
  );
};

export default AppLayout;
