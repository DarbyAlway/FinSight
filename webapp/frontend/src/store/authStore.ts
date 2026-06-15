import { create } from 'zustand';
import type { AuthStatus, User } from '../types';
import * as authApi from '../api/auth';

interface AuthState {
  user: User | null;
  status: AuthStatus;
  loadMe: () => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  status: 'loading',
  loadMe: async () => {
    try { set({ user: await authApi.getMe(), status: 'authed' }); }
    catch { set({ user: null, status: 'anon' }); }
  },
  login: async (email, password) => set({ user: await authApi.login(email, password), status: 'authed' }),
  register: async (email, password) => set({ user: await authApi.register(email, password), status: 'authed' }),
  logout: async () => { await authApi.logout(); set({ user: null, status: 'anon' }); },
}));
