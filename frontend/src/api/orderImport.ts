import { http } from './http';
import type { Order, ParsedOrderDraft } from '../types';

/** Upload a quotation PDF and get back a parsed, catalog-matched draft (no persistence). */
export async function parseOrderPdf(file: File): Promise<ParsedOrderDraft> {
  const form = new FormData();
  form.append('file', file);
  const { data } = await http.post<ParsedOrderDraft>('/orders/import/parse', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

export interface ConfirmLine {
  sku: string;
  name?: string;
  unit?: string;
  ordered_quantity: number;
  product_id?: string | null;
}

/** Create the order from the reviewed draft. */
export async function confirmOrderImport(payload: {
  erp_order_number: string;
  customer?: string;
  customer_rut?: string;
  order_date?: string;
  doc_type?: string;
  lines: ConfirmLine[];
}): Promise<Order> {
  const { data } = await http.post<Order>('/orders/import/confirm', payload);
  return data;
}
