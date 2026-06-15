import { beforeEach, vi } from 'vitest';
vi.mock('../api/auth', () => ({
  getMe: vi.fn(async () => ({ id: 'u1', email: 'u@x.com', is_owner: false, tokens_used: 0 })),
  login: vi.fn(async () => ({ id: 'u1', email: 'u@x.com', is_owner: false, tokens_used: 0 })),
  register: vi.fn(async () => ({ id: 'u1', email: 'u@x.com', is_owner: false, tokens_used: 0 })),
  logout: vi.fn(async () => {}),
}));
import { useAuthStore } from '../store/authStore';
import * as authApi from '../api/auth';

beforeEach(() => { useAuthStore.setState({ user: null, status: 'loading' }); vi.clearAllMocks(); });

test('loadMe sets authed when a session exists', async () => {
  await useAuthStore.getState().loadMe();
  expect(useAuthStore.getState().status).toBe('authed');
  expect(useAuthStore.getState().user?.email).toBe('u@x.com');
});

test('loadMe sets anon on 401', async () => {
  (authApi.getMe as any).mockRejectedValueOnce(new Error('401'));
  await useAuthStore.getState().loadMe();
  expect(useAuthStore.getState().status).toBe('anon');
});

test('logout clears the user', async () => {
  useAuthStore.setState({ user: { id: 'u1', email: 'u@x.com', is_owner: false, tokens_used: 0 }, status: 'authed' });
  await useAuthStore.getState().logout();
  expect(useAuthStore.getState().status).toBe('anon');
  expect(useAuthStore.getState().user).toBeNull();
});
