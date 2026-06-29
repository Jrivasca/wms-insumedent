import { http } from './http';
import type { SyncJob } from '../types';

export async function listSyncJobs(): Promise<SyncJob[]> {
  const { data } = await http.get<SyncJob[]>('/sync-jobs');
  return data;
}

export async function retrySyncJob(id: string): Promise<SyncJob> {
  const { data } = await http.post<SyncJob>(`/sync-jobs/${id}/retry`);
  return data;
}

export async function cancelSyncJob(id: string): Promise<SyncJob> {
  const { data } = await http.post<SyncJob>(`/sync-jobs/${id}/cancel`);
  return data;
}
