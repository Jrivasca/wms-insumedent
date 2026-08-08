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

export interface LocationInput {
  code?: string;
  name?: string;
  type?: string;
  zone?: string;
  aisle?: string;
  rack?: string;
  level?: string;
  bin?: string;
  is_active?: boolean;
}

export async function createLocation(
  payload: LocationInput & { warehouse_id: string; code: string }
): Promise<Location> {
  const { data } = await http.post<Location>('/locations', payload);
  return data;
}

export async function updateLocation(id: string, payload: LocationInput): Promise<Location> {
  const { data } = await http.put<Location>(`/locations/${id}`, payload);
  return data;
}
