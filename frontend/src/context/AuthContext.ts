import { createContext } from 'react';
import type { BootstrapPayload, UserAccount } from '../services/api';

export interface AuthContextType {
  user: UserAccount | null;
  bootstrapRequired: boolean;
  isLoading: boolean;
  isInitialized: boolean;
  error: string | null;
  checkAuthStatus: () => Promise<void>;
  submitBootstrap: (payload: BootstrapPayload) => Promise<boolean>;
  login: (pin: string) => Promise<boolean>;
  logout: () => Promise<void>;
  clearError: () => void;
}

export const AuthContext = createContext<AuthContextType | undefined>(undefined);
