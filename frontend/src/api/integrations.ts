import { http } from './http';
import type { DefontanaStatus } from '../types';

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

export async function syncWarehouses(): Promise<{ status: string; summary?: unknown }> {
  const { data } = await http.post('/integrations/defontana/sync-warehouses');
  return data;
}

export async function syncOrders(): Promise<{ status: string; summary?: unknown }> {
  const { data } = await http.post('/integrations/defontana/sync-orders');
  return data;
}
