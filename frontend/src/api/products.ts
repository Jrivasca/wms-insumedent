import { http } from './http';
import type { Barcode, Page, Product } from '../types';

export async function listProducts(
  search?: string,
  limit?: number,
  offset?: number
): Promise<Page<Product>> {
  const params: Record<string, string | number> = {};
  if (search) params.search = search;
  if (limit != null) params.limit = limit;
  if (offset != null) params.offset = offset;
  const { data } = await http.get<Page<Product>>('/products', { params });
  return data;
}

export async function createProduct(payload: {
  sku: string;
  name: string;
  description?: string;
  unit?: string;
  brand?: string;
  category?: string;
  barcode?: string;
  cost?: number;
  sale_price?: number;
}): Promise<Product> {
  const { data } = await http.post<Product>('/products', payload);
  return data;
}

export async function getProduct(id: string): Promise<Product> {
  const { data } = await http.get<Product>(`/products/${id}`);
  return data;
}

export interface CatalogImportReport {
  applied: boolean;
  rows?: number;
  created?: number;
  updated?: number;
  barcodes_added?: number;
  rejected?: { row: number; reason: string }[];
  error?: string;
}

/** Import/actualizar el catálogo desde un Excel (.xlsx). */
export async function importCatalog(file: File): Promise<CatalogImportReport> {
  const form = new FormData();
  form.append('file', file);
  const { data } = await http.post<CatalogImportReport>('/products/import', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

export async function getProductByBarcode(barcode: string): Promise<Product> {
  const { data } = await http.get<Product>(`/products/barcode/${encodeURIComponent(barcode)}`);
  return data;
}

export async function addBarcode(
  productId: string,
  barcode: string,
  type?: string
): Promise<Barcode> {
  const { data } = await http.post<Barcode>(`/products/${productId}/barcodes`, {
    barcode,
    type,
  });
  return data;
}
