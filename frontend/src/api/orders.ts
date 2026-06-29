import { http } from './http';
import type { Order, PickingTask } from '../types';

export async function listOrders(): Promise<Order[]> {
  const { data } = await http.get<Order[]>('/orders');
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

export async function createPicking(orderId: string): Promise<PickingTask> {
  const { data } = await http.post<PickingTask>(`/orders/${orderId}/create-picking`);
  return data;
}
