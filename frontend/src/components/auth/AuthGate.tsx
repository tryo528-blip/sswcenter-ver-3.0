import React from 'react';
import { useAuth } from '../../context/useAuth';
import BootstrapForm from './BootstrapForm';
import LoginForm from './LoginForm';

export const AuthGate: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { user, bootstrapRequired, isLoading, isInitialized } = useAuth();

  if (isLoading && (!isInitialized || user)) {
    return (
      <div className="auth-loading-container" data-testid="auth-loading">
        <div className="auth-spinner" />
        <p>인증 정보를 확인 중입니다...</p>
      </div>
    );
  }

  if (bootstrapRequired) {
    return <BootstrapForm />;
  }

  if (!user) {
    return <LoginForm />;
  }

  return <>{children}</>;
};

export default AuthGate;
