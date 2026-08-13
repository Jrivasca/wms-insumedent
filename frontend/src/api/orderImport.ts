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

export interface ImportConfirmPayload {
  erp_order_number: string;
  customer?: string;
  customer_rut?: string;
  order_date?: string;
  doc_type?: string;
  lines: ConfirmLine[];
}

/** Create the order from the reviewed draft. */
export async function confirmOrderImport(payload: ImportConfirmPayload): Promise<Order> {
  const { data } = await http.post<Order>('/orders/import/confirm', payload);
  return data;
}

// --- Cola de revisión del folder-watch (Plan 1 Fase 1) ---------------------
export interface ImportDraftSummary {
  id: string;
  erp_order_number?: string | null;
  customer?: string | null;
  line_count?: number;
  problem_lines?: number;
  file_name?: string | null;
  doc_type?: string | null;
  created_at?: string;
}

export async function listImportDrafts(): Promise<ImportDraftSummary[]> {
  const { data } = await http.get<ImportDraftSummary[]>('/orders/import/drafts');
  return data;
}

export async function importDraftsCount(): Promise<number> {
  const { data } = await http.get<{ count: number }>('/orders/import/drafts/count');
  return data.count;
}

export async function getImportDraft(
  id: string
): Promise<ParsedOrderDraft & { id: string; file_name?: string }> {
  const { data } = await http.get<ParsedOrderDraft & { id: string; file_name?: string }>(
    `/orders/import/drafts/${id}`
  );
  return data;
}

export async function confirmImportDraft(id: string, payload: ImportConfirmPayload): Promise<Order> {
  const { data } = await http.post<Order>(`/orders/import/drafts/${id}/confirm`, payload);
  return data;
}

export async function discardImportDraft(id: string): Promise<void> {
  await http.post(`/orders/import/drafts/${id}/discard`);
}
