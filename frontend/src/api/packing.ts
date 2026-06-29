import { http } from './http';
import type { PackageBulto, PackingTask, ScanResult } from '../types';

export async function listPackingTasks(params?: {
  assigned_to?: string;
}): Promise<PackingTask[]> {
  const { data } = await http.get<PackingTask[]>('/packing/tasks', { params });
  return data;
}

export async function getPackingTask(id: string): Promise<PackingTask> {
  const { data } = await http.get<PackingTask>(`/packing/tasks/${id}`);
  return data;
}

export async function startPacking(id: string): Promise<PackingTask> {
  const { data } = await http.post<PackingTask>(`/packing/tasks/${id}/start`);
  return data;
}

export async function scanPacking(
  id: string,
  payload: { barcode: string; quantity: number; package_id?: string }
): Promise<ScanResult> {
  const { data } = await http.post<ScanResult>(`/packing/tasks/${id}/scan`, payload);
  return data;
}

export async function createPackage(
  id: string,
  payload?: { label?: string }
): Promise<PackageBulto> {
  const { data } = await http.post<PackageBulto>(`/packing/tasks/${id}/create-package`, payload ?? {});
  return data;
}

export async function completePacking(id: string): Promise<PackingTask> {
  const { data } = await http.post<PackingTask>(`/packing/tasks/${id}/complete`);
  return data;
}
