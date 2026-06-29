import { http } from './http';
import type { Barcode, Product } from '../types';

export async function listProducts(search?: string): Promise<Product[]> {
  const { data } = await http.get<Product[]>('/products', {
    params: search ? { search } : undefined,
  });
  return data;
}

export async function getProduct(id: string): Promise<Product> {
  const { data } = await http.get<Product>(`/products/${id}`);
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
