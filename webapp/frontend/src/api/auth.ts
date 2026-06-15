import type { User } from '../types';

async function jsonOrThrow(r: Response): Promise<User> {
  if (!r.ok) throw new Error(String(r.status));
  return r.json();
}

export async function getMe(): Promise<User> {
  return jsonOrThrow(await fetch('/auth/me', { credentials: 'include' }));
}
export async function login(email: string, password: string): Promise<User> {
  return jsonOrThrow(await fetch('/auth/login', {
    method: 'POST', credentials: 'include',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password }),
  }));
}
export async function register(email: string, password: string): Promise<User> {
  return jsonOrThrow(await fetch('/auth/register', {
    method: 'POST', credentials: 'include',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password }),
  }));
}
export async function logout(): Promise<void> {
  await fetch('/auth/logout', { method: 'POST', credentials: 'include' });
}
