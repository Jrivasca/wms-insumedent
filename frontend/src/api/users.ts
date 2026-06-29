import { http } from './http';
import type { User } from '../types';

export async function listUsers(): Promise<User[]> {
  const { data } = await http.get<User[]>('/users');
  return data;
}

export async function getUser(id: string): Promise<User> {
  const { data } = await http.get<User>(`/users/${id}`);
  return data;
}

export async function createUser(payload: {
  name: string;
  email: string;
  password: string;
  role: string;
  allowed_warehouse_ids?: string[];
}): Promise<User> {
  const { data } = await http.post<User>('/users', payload);
  return data;
}

export async function updateUser(id: string, payload: Partial<User>): Promise<User> {
  const { data } = await http.patch<User>(`/users/${id}`, payload);
  return data;
}
