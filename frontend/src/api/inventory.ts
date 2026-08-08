import { http } from './http';
import type { InventoryBalance, InventoryMovement, Page } from '../types';

export async function listBalances(params?: {
  product_id?: string;
  warehouse_id?: string;
  location_id?: string;
  limit?: number;
  offset?: number;
}): Promise<Page<InventoryBalance>> {
  const { data } = await http.get<Page<InventoryBalance>>('/inventory/balances', { params });
  return data;
}

export async function listMovements(params?: {
  product_id?: string;
  limit?: number;
  offset?: number;
}): Promise<Page<InventoryMovement>> {
  const { data } = await http.get<Page<InventoryMovement>>('/inventory/movements', { params });
  return data;
}

export async function createReception(payload: {
  product_id: string;
  warehouse_id: string;
  location_id: string;
  quantity: number;
  reference?: string;
  lot_number?: string;
  serial_number?: string;
  sync_erp?: boolean;
}): Promise<{ balance: InventoryBalance | null; movement: InventoryMovement; sync_job_id?: string | null }> {
  const { data } = await http.post('/inventory/receptions', payload);
  return data;
}

export async function createAdjustment(payload: {
  product_id: string;
  warehouse_id: string;
  location_id: string;
  quantity: number;
  reason: string;
  lot_number?: string;
  serial_number?: string;
}): Promise<InventoryBalance> {
  const { data } = await http.post<InventoryBalance>('/inventory/adjustments', payload);
  return data;
}

export async function createTransfer(payload: {
  product_id: string;
  warehouse_id: string;
  from_location_id: string;
  to_location_id: string;
  quantity: number;
}): Promise<{ status: string }> {
  const { data } = await http.post<{ status: string }>('/inventory/transfers', payload);
  return data;
}
