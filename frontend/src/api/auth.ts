import { http } from './http';
import type { LoginResponse, User } from '../types';

export async function login(email: string, password: string): Promise<LoginResponse> {
  const { data } = await http.post<LoginResponse>('/auth/login', { email, password });
  return data;
}

export async function me(): Promise<User> {
  const { data } = await http.get<User>('/auth/me');
  return data;
}

export async function logout(): Promise<void> {
  try {
    await http.post('/auth/logout');
  } catch {
    // best-effort
  }
}
