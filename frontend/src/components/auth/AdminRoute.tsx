import React from 'react';
import { Navigate } from 'react-router';
import { useAuth } from '../../context/useAuth';

export const AdminRoute: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { user } = useAuth();
  if (user?.role_code !== 'ADMIN') {
    return <Navigate to="/dashboard" replace />;
  }
  return <>{children}</>;
};

export default AdminRoute;
