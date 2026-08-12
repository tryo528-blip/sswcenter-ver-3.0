import React, { useCallback, useEffect, useRef, useState } from 'react';
import type { BootstrapPayload, UserAccount } from '../services/api';
import {
  ApiError,
  AUTH_UNAUTHORIZED_EVENT,
  beginAuthTransition,
  fetchBootstrapStatus,
  getMe,
  markAuthReady,
  postBootstrap,
  postLogin,
  postLogout,
} from '../services/api';
import { AuthContext } from './AuthContext';

const DEV_PREVIEW_ACCOUNT: UserAccount = {
  id: 0,
  display_name: '홍길동 관리자',
  role_code: 'ADMIN',
};

const devLoginBypassEnabled =
  import.meta.env.DEV && import.meta.env.VITE_DEV_LOGIN_BYPASS === 'true';

function isAbortError(value: unknown): boolean {
  return value instanceof Error && value.name === 'AbortError';
}

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<UserAccount | null>(null);
  const [bootstrapRequired, setBootstrapRequired] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [isInitialized, setIsInitialized] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const operationRef = useRef(0);
  const logoutOperationRef = useRef<number | null>(null);

  const checkAuthStatus = useCallback(async () => {
    logoutOperationRef.current = null;
    const operation = ++operationRef.current;
    setIsLoading(true);
    setError(null);

    if (devLoginBypassEnabled) {
      setBootstrapRequired(false);
      setUser(DEV_PREVIEW_ACCOUNT);
      setIsInitialized(true);
      setIsLoading(false);
      return;
    }

    try {
      const statusResponse = await fetchBootstrapStatus();
      if (operationRef.current !== operation) return;
      if (statusResponse.bootstrap_required) {
        setBootstrapRequired(true);
        setUser(null);
        return;
      }

      setBootstrapRequired(false);
      try {
        const meResponse = await getMe();
        if (operationRef.current !== operation) return;
        setUser(meResponse.account);
      } catch (requestError: unknown) {
        if (operationRef.current !== operation || isAbortError(requestError)) return;
        setUser(null);
        if (requestError instanceof ApiError && requestError.status === 401) {
          beginAuthTransition();
        } else {
          setError('로그인 상태를 확인할 수 없습니다. 서버 연결을 확인해주세요.');
        }
      }
    } catch (requestError: unknown) {
      if (operationRef.current !== operation || isAbortError(requestError)) return;
      setUser(null);
      setError('시스템 인증 상태를 확인하는 중 오류가 발생했습니다.');
    } finally {
      if (operationRef.current === operation) {
        setIsLoading(false);
        setIsInitialized(true);
      }
    }
  }, []);

  useEffect(() => {
    const handleUnauthorized = () => {
      operationRef.current += 1;
      if (devLoginBypassEnabled) {
        // Data APIs can still report a stale/missing cookie while the local
        // development preview is running. Keep the explicit preview account
        // visible instead of sending the user back to the PIN screen.
        setBootstrapRequired(false);
        setUser(DEV_PREVIEW_ACCOUNT);
        setIsInitialized(true);
        setIsLoading(false);
        setError(null);
        return;
      }
      setUser(null);
    };
    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, handleUnauthorized);
    void checkAuthStatus();
    return () => window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, handleUnauthorized);
  }, [checkAuthStatus]);

  const submitBootstrap = async (payload: BootstrapPayload): Promise<boolean> => {
    logoutOperationRef.current = null;
    const operation = ++operationRef.current;
    setIsLoading(true);
    setError(null);
    try {
      await postBootstrap(payload);
      if (operationRef.current !== operation) return false;
      setBootstrapRequired(false);
      setUser(null);
      return true;
    } catch (requestError: unknown) {
      if (operationRef.current !== operation || isAbortError(requestError)) return false;
      const message =
        requestError instanceof Error ? requestError.message : '초기 설정 저장에 실패했습니다.';
      setError(message === 'invalid_pin' ? 'PIN 번호가 올바르지 않습니다.' : message);
      return false;
    } finally {
      if (operationRef.current === operation) setIsLoading(false);
    }
  };

  const login = async (pin: string): Promise<boolean> => {
    logoutOperationRef.current = null;
    beginAuthTransition();
    const operation = ++operationRef.current;
    setIsLoading(true);
    setError(null);
    try {
      const response = await postLogin(pin);
      if (operationRef.current !== operation) return false;
      setUser(response.account);
      markAuthReady();
      return true;
    } catch (requestError: unknown) {
      if (operationRef.current !== operation || isAbortError(requestError)) return false;
      setUser(null);
      if (requestError instanceof ApiError) {
        if (requestError.status === 401) {
          setError('PIN 번호가 올바르지 않습니다.');
        } else if (requestError.status === 423) {
          setError('로그인 실패가 누적되어 계정이 잠겼습니다. 잠시 후 다시 시도해주세요.');
        } else if (requestError.status === 429) {
          setError('로그인 시도가 너무 많습니다. 잠시 후 다시 시도해주세요.');
        } else {
          setError(requestError.message);
        }
      } else {
        setError('로그인 처리에 실패했습니다.');
      }
      return false;
    } finally {
      if (operationRef.current === operation) setIsLoading(false);
    }
  };

  const logout = async (): Promise<void> => {
    beginAuthTransition();
    const operation = ++operationRef.current;
    logoutOperationRef.current = operation;
    setIsLoading(true);
    setError(null);
    try {
      await postLogout();
      if (operationRef.current !== operation) return;
      setUser(null);
    } catch (requestError: unknown) {
      if (operationRef.current !== operation || isAbortError(requestError)) return;
      if (requestError instanceof ApiError && requestError.status === 401) {
        setUser(null);
      } else {
        setError('로그아웃에 실패했습니다. 연결을 확인한 뒤 다시 시도해주세요.');
        markAuthReady();
      }
    } finally {
      const ownsLogoutOperation = logoutOperationRef.current === operation;
      if (ownsLogoutOperation) {
        logoutOperationRef.current = null;
      }
      if (operationRef.current === operation || ownsLogoutOperation) setIsLoading(false);
    }
  };

  const clearError = () => setError(null);

  return (
    <AuthContext.Provider
      value={{
        user,
        bootstrapRequired,
        isLoading,
        isInitialized,
        error,
        checkAuthStatus,
        submitBootstrap,
        login,
        logout,
        clearError,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};
