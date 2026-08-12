import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router';
import { AuthProvider } from './context/AuthProvider';
import AdminRoute from './components/auth/AdminRoute';
import AuthGate from './components/auth/AuthGate';
import AppLayout from './components/layout/AppLayout';
import DashboardPage from './pages/DashboardPage';
import RecipientsPage from './pages/RecipientsPage';
import StaffPage from './pages/StaffPage';
import SocialWorkersPage from './pages/SocialWorkersPage';
import CopayPage from './pages/CopayPage';
import IOPage from './pages/IOPage';
import FileboxPage from './pages/FileboxPage';
import SettingsPage from './pages/SettingsPage';
import SchedulePopupPage from './pages/SchedulePopupPage';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: false },
    mutations: { retry: false },
  },
});

export const App: React.FC = () => {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <AuthGate>
            <Routes>
              <Route path="/schedules/:scheduleKind" element={<SchedulePopupPage />} />
              <Route path="/" element={<AppLayout />}>
                <Route index element={<Navigate to="/dashboard" replace />} />
                <Route path="dashboard" element={<DashboardPage />} />
                <Route path="recipients" element={<RecipientsPage />} />
                <Route path="staff" element={<StaffPage />} />
                <Route path="social-workers" element={<SocialWorkersPage />} />
                <Route path="copay" element={<CopayPage />} />
                <Route path="io" element={<IOPage />} />
                <Route path="filebox" element={<FileboxPage />} />
                <Route
                  path="settings"
                  element={
                    <AdminRoute>
                      <SettingsPage />
                    </AdminRoute>
                  }
                />
                <Route path="*" element={<Navigate to="/dashboard" replace />} />
              </Route>
            </Routes>
          </AuthGate>
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  );
};

export default App;
