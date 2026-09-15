import { http } from './http';
import type { DefontanaStatus, ErpStockComparison } from '../types';

export interface DefontanaConfig {
  environment: string;
  client?: string;
  company?: string;
  user?: string;
  password?: string;
  email?: string;
  email_password?: string;
  auth_mode?: string;
}

export async function getDefontanaStatus(): Promise<DefontanaStatus> {
  const { data } = await http.get<DefontanaStatus>('/integrations/defontana/status');
  return data;
}

export async function configureDefontana(payload: DefontanaConfig): Promise<DefontanaStatus> {
  const { data } = await http.post<DefontanaStatus>('/integrations/defontana/configure', payload);
  return data;
}

export async function checkDefontana(): Promise<{ status: string; message?: string }> {
  const { data } = await http.post<{ status: string; message?: string }>(
    '/integrations/defontana/check'
  );
  return data;
}

export async function syncProducts(): Promise<{ status: string; summary?: unknown }> {
  const { data } = await http.post('/integrations/defontana/sync-products');
  return data;
}

export async function syncOrders(): Promise<{ status: string; summary?: unknown }> {
  const { data } = await http.post('/integrations/defontana/sync-orders');
  return data;
}

/** Trae la foto de stock de Defontana (no modifica el stock del WMS). */
export async function syncStock(): Promise<{ status: string; summary?: { products: number; rows: number } }> {
  const { data } = await http.post('/integrations/defontana/sync-stock');
  return data;
}

export async function getStockComparison(params: {
  only_diff?: boolean;
  q?: string;
  limit?: number;
  offset?: number;
}): Promise<ErpStockComparison> {
  const { data } = await http.get<ErpStockComparison>('/integrations/defontana/stock-comparison', {
    params,
  });
  return data;
}
