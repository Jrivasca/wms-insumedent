import { http } from './http';
import type { InventoryBalance, InventoryMovement } from '../types';

export async function listBalances(params?: {
  product_id?: string;
  warehouse_id?: string;
  location_id?: string;
}): Promise<InventoryBalance[]> {
  const { data } = await http.get<InventoryBalance[]>('/inventory/balances', { params });
  return data;
}

export async function listMovements(params?: {
  product_id?: string;
}): Promise<InventoryMovement[]> {
  const { data } = await http.get<InventoryMovement[]>('/inventory/movements', { params });
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
