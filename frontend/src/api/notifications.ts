import { http } from './http';
import type { AppNotification, Page } from '../types';

export async function listNotifications(params?: {
  unread?: boolean;
  limit?: number;
  offset?: number;
}): Promise<Page<AppNotification>> {
  const { data } = await http.get<Page<AppNotification>>('/notifications', { params });
  return data;
}

export async function unreadCount(): Promise<number> {
  const { data } = await http.get<{ count: number }>('/notifications/unread-count');
  return data.count;
}

export async function markRead(id: string): Promise<void> {
  await http.post(`/notifications/${id}/read`);
}

export async function markAllRead(): Promise<void> {
  await http.post('/notifications/read-all');
}
