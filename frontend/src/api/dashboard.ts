import { http } from './http';
import type { DashboardStats } from '../types';

export async function getDashboardStats(): Promise<DashboardStats> {
  const { data } = await http.get<DashboardStats>('/dashboard/stats');
  return data;
}
