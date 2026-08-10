import { http } from './http';
import type { Dispatch, Page } from '../types';

export async function listDispatches(params?: {
  limit?: number;
  offset?: number;
}): Promise<Page<Dispatch>> {
  const { data } = await http.get<Page<Dispatch>>('/dispatches', { params });
  return data;
}

export async function getDispatch(id: string): Promise<Dispatch> {
  const { data } = await http.get<Dispatch>(`/dispatches/${id}`);
  return data;
}

export async function dispatchOrder(
  orderId: string,
  payload: { guide_number?: string; carrier?: string; tracking_number?: string }
): Promise<Dispatch> {
  const { data } = await http.post<Dispatch>(`/orders/${orderId}/dispatch`, payload);
  return data;
}

export async function cancelDispatch(orderId: string): Promise<unknown> {
  const { data } = await http.post(`/orders/${orderId}/dispatch/cancel`);
  return data;
}
