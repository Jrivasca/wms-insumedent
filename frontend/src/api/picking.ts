import { http } from './http';
import type { PickingTask, ScanResult } from '../types';

export async function listPickingTasks(params?: {
  assigned_to?: string;
  status?: string;
}): Promise<PickingTask[]> {
  const { data } = await http.get<PickingTask[]>('/picking/tasks', { params });
  return data;
}

export async function getPickingTask(id: string): Promise<PickingTask> {
  const { data } = await http.get<PickingTask>(`/picking/tasks/${id}`);
  return data;
}

export async function startPicking(id: string): Promise<PickingTask> {
  const { data } = await http.post<PickingTask>(`/picking/tasks/${id}/start`);
  return data;
}

export async function scanPicking(
  id: string,
  payload: { barcode: string; quantity: number; location_id?: string }
): Promise<ScanResult> {
  const { data } = await http.post<ScanResult>(`/picking/tasks/${id}/scan`, payload);
  return data;
}

export async function markMissing(
  id: string,
  payload: { sku: string; reason: string }
): Promise<PickingTask> {
  const { data } = await http.post<PickingTask>(`/picking/tasks/${id}/mark-missing`, payload);
  return data;
}

export async function completePicking(
  id: string,
  allowPartial = false
): Promise<PickingTask> {
  const { data } = await http.post<PickingTask>(`/picking/tasks/${id}/complete`, {
    allow_partial: allowPartial,
  });
  return data;
}
