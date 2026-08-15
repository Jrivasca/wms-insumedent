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

/** Las guías (despachos) de un pedido, más recientes primero. */
export async function listOrderDispatches(orderId: string): Promise<Page<Dispatch>> {
  const { data } = await http.get<Page<Dispatch>>(`/orders/${orderId}/dispatches`);
  return data;
}

export async function dispatchOrder(
  orderId: string,
  payload: {
    guide_number?: string;
    carrier?: string;
    tracking_number?: string;
    // Despacho dividido (opcional): cantidades por SKU o bultos específicos.
    lines?: { sku: string; quantity: number }[];
    package_ids?: string[];
  }
): Promise<Dispatch> {
  const { data } = await http.post<Dispatch>(`/orders/${orderId}/dispatch`, payload);
  return data;
}

/** Anular TODAS las guías de un pedido (vuelve a "listo para despacho"). */
export async function cancelDispatch(orderId: string): Promise<unknown> {
  const { data } = await http.post(`/orders/${orderId}/dispatch/cancel`);
  return data;
}

/** Anular UNA guía puntual (el resto del pedido sigue su curso). */
export async function cancelOneDispatch(dispatchId: string): Promise<unknown> {
  const { data } = await http.post(`/dispatches/${dispatchId}/cancel`);
  return data;
}
