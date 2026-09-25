import { http } from './http';
import type { Page, PickingTask, ScanResult } from '../types';

export async function listPickingTasks(params?: {
  assigned_to?: string;
  status?: string;
  limit?: number;
  offset?: number;
}): Promise<Page<PickingTask>> {
  const { data } = await http.get<Page<PickingTask>>('/picking/tasks', { params });
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
  payload: { barcode: string; quantity: number; location_id?: string; lot_number?: string }
): Promise<ScanResult> {
  const { data } = await http.post<ScanResult>(`/picking/tasks/${id}/scan`, payload);
  return data;
}

export interface PickLot {
  location_id: string;
  location_code: string;
  lot_number: string | null;
  expiration_date: string | null;
  quantity_on_hand: number;
  quantity_available: number;
}

export interface LineLots {
  line_id: string;
  manages_lots: boolean;
  lots: PickLot[];
}

/** Lotes disponibles (FEFO) para elegir al pickear una línea. */
export async function getLineLots(id: string, lineId: string): Promise<LineLots> {
  const { data } = await http.get<LineLots>(`/picking/tasks/${id}/lines/${lineId}/lots`);
  return data;
}

export interface ErpLot {
  lot_number: string;
  expiration_date: string | null;
  stock: number | null;
  storage_code: string | null;
}

export interface LineErpLots {
  line_id: string;
  sku: string;
  lots: ErpLot[];
}

/** Lotes que Defontana informa para el producto (candidatos correctos al corregir). */
export async function getLineErpLots(id: string, lineId: string): Promise<LineErpLots> {
  const { data } = await http.get<LineErpLots>(`/picking/tasks/${id}/lines/${lineId}/erp-lots`);
  return data;
}

/** Corregir el lote mal ingresado de un saldo por el correcto (Parte 3, opción A). */
export async function correctLot(
  id: string,
  lineId: string,
  payload: {
    location_id: string;
    from_lot_number: string | null;
    to_lot_number: string;
    to_expiration_date?: string | null;
  }
): Promise<{ line_id: string; balance: unknown }> {
  const { data } = await http.post(`/picking/tasks/${id}/lines/${lineId}/correct-lot`, payload);
  return data;
}

/** Actualizar la foto de lotes desde Defontana (no mueve stock). */
export async function syncLots(): Promise<{ status: string; summary: { batches: number } }> {
  const { data } = await http.post('/picking/sync-lots');
  return data;
}

export async function markMissing(
  id: string,
  payload: { sku: string; reason: string }
): Promise<PickingTask> {
  const { data } = await http.post<PickingTask>(`/picking/tasks/${id}/mark-missing`, payload);
  return data;
}

export async function resetPickingLine(
  id: string,
  payload: { sku: string }
): Promise<PickingTask> {
  const { data } = await http.post<PickingTask>(`/picking/tasks/${id}/reset-line`, payload);
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
