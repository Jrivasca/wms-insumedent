import { http } from './http';
import type {
  ExpiringPage,
  InventoryBalance,
  InventoryMovement,
  Page,
  PutawayResult,
} from '../types';

export async function listBalances(params?: {
  product_id?: string;
  warehouse_id?: string;
  location_id?: string;
  /** Busca en SKU, nombre, código de barras, lote y serie. Lo resuelve el servidor. */
  q?: string;
  /** Por defecto el backend esconde las filas en cero. */
  positive_only?: boolean;
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
  expiration_date?: string;
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

/** Vencido y por vencer, en orden FEFO, con el resumen por tramo. */
export async function listExpiring(params?: {
  days?: number;
  q?: string;
  warehouse_id?: string;
  location_id?: string;
  limit?: number;
  offset?: number;
}): Promise<ExpiringPage> {
  const { data } = await http.get<ExpiringPage>('/inventory/expiring', { params });
  return data;
}

/** Ubicar stock: mueve un saldo exacto (con su lote, serie y vencimiento) a otra ubicación
 *  de la misma bodega. Es interno del WMS: no viaja nada a Defontana. */
export async function putawayBalance(payload: {
  balance_id: string;
  to_location_id: string;
  quantity: number;
}): Promise<PutawayResult> {
  const { data } = await http.post<PutawayResult>('/inventory/putaway', payload);
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
