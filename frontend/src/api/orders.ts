import { http } from './http';
import type { Order, Page, PickingTask } from '../types';

export async function listOrders(params?: {
  status?: string;
  limit?: number;
  offset?: number;
}): Promise<Page<Order>> {
  const { data } = await http.get<Page<Order>>('/orders', { params });
  return data;
}

export async function getOrder(id: string): Promise<Order> {
  const { data } = await http.get<Order>(`/orders/${id}`);
  return data;
}

export async function createOrder(payload: {
  erp_order_number: string;
  customer?: string;
  lines: { sku: string; name?: string; unit?: string; ordered_quantity: number }[];
}): Promise<Order> {
  const { data } = await http.post<Order>('/orders', payload);
  return data;
}

export async function updateOrder(
  id: string,
  payload: {
    customer?: string;
    lines?: { sku: string; name?: string; unit?: string; ordered_quantity: number }[];
  }
): Promise<Order> {
  const { data } = await http.put<Order>(`/orders/${id}`, payload);
  return data;
}

export async function createPicking(orderId: string): Promise<PickingTask> {
  const { data } = await http.post<PickingTask>(`/orders/${orderId}/create-picking`);
  return data;
}

export async function reopenPacking(orderId: string): Promise<unknown> {
  const { data } = await http.post(`/orders/${orderId}/reopen-packing`);
  return data;
}

export async function reopenPicking(orderId: string): Promise<unknown> {
  const { data } = await http.post(`/orders/${orderId}/reopen-picking`);
  return data;
}
