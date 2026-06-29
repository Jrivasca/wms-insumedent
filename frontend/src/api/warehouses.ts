import { http } from './http';
import type { Location, Warehouse } from '../types';

export async function listWarehouses(): Promise<Warehouse[]> {
  const { data } = await http.get<Warehouse[]>('/warehouses');
  return data;
}

export async function createWarehouse(payload: {
  name: string;
  erp_storage_code?: string;
  type?: string;
}): Promise<Warehouse> {
  const { data } = await http.post<Warehouse>('/warehouses', payload);
  return data;
}

export async function listLocations(warehouseId?: string): Promise<Location[]> {
  const { data } = await http.get<Location[]>('/locations', {
    params: warehouseId ? { warehouse_id: warehouseId } : undefined,
  });
  return data;
}

export async function listWarehouseLocations(warehouseId: string): Promise<Location[]> {
  const { data } = await http.get<Location[]>(`/warehouses/${warehouseId}/locations`);
  return data;
}

export async function createLocation(payload: {
  warehouse_id: string;
  code: string;
  name?: string;
  type?: string;
}): Promise<Location> {
  const { data } = await http.post<Location>('/locations', payload);
  return data;
}
