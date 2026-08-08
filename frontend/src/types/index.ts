export type Role = 'admin' | 'supervisor' | 'picker' | 'packer' | 'operario' | string;

/** Paginated list envelope returned by every `list*` endpoint. */
export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface User {
  id: string;
  name: string;
  email: string;
  role: Role;
  tenant_id?: string;
  allowed_warehouse_ids?: string[];
  is_active?: boolean;
}

export interface Barcode {
  barcode: string;
  type?: string;
}

export interface Product {
  id: string;
  sku: string;
  name: string;
  description?: string;
  unit?: string;
  brand?: string;
  category?: string;
  barcodes: Barcode[];
  uses_lots?: boolean;
  uses_serials?: boolean;
  is_active?: boolean;
}

export interface Warehouse {
  id: string;
  name: string;
  erp_storage_code?: string;
  type?: string;
  is_active?: boolean;
}

export interface Location {
  id: string;
  warehouse_id: string;
  code: string;
  name?: string;
  type?: string;
  zone?: string;
  aisle?: string;
  rack?: string;
  level?: string;
  bin?: string;
  is_active?: boolean;
}

export interface DashboardStats {
  orders: {
    total: number;
    por_procesar: number;
    en_proceso: number;
    listos_despacho: number;
    despachados: number;
    despachados_hoy: number;
    error_cancelados: number;
    por_estado: Record<string, number>;
  };
  inventory: {
    productos: number;
    sin_stock: number;
    con_stock: number;
    ubicaciones: number;
  };
  operations: {
    picking_abiertas: number;
    packing_abiertas: number;
    sync_pendientes: number;
  };
}

export interface InventoryBalance {
  id: string;
  product_id: string;
  product_name: string;
  sku: string;
  warehouse_id: string;
  location_id: string;
  location_code?: string;
  lot_number?: string;
  serial_number?: string;
  quantity_on_hand: number;
  quantity_reserved: number;
  quantity_available: number;
  quantity_blocked: number;
}

export interface InventoryMovement {
  id: string;
  movement_type: string;
  product_id: string;
  sku: string;
  from_location_id?: string;
  to_location_id?: string;
  quantity: number;
  reason?: string;
  created_by?: string;
  created_at: string;
}

export type OrderStatus =
  | 'pending'
  | 'picking'
  | 'picked'
  | 'packing'
  | 'packed'
  | 'ready_to_dispatch'
  | 'dispatched'
  | 'cancelled'
  | string;

export interface OrderLine {
  line_id: string;
  product_id: string;
  sku: string;
  name: string;
  unit?: string;
  ordered_quantity: number;
  picked_quantity: number;
  packed_quantity: number;
  status?: string;
}

export interface Order {
  id: string;
  erp_order_number: string;
  customer: string;
  status: OrderStatus;
  order_date?: string;
  delivery_date?: string;
  lines: OrderLine[];
}

// --- Importación de pedido desde PDF (cotización INSUMEDENT) ---

export type MatchStatus = 'matched' | 'ambiguous' | 'unmatched' | 'invalid';

export interface LineCandidate {
  product_id: string;
  sku: string;
  name: string;
}

export interface ParsedOrderLine {
  raw_text?: string | null;
  item?: number | null;
  sku?: string | null;
  name?: string | null;
  unit: string;
  ordered_quantity?: number | null;
  match_status: MatchStatus;
  match_by?: string | null;
  product_id?: string | null;
  candidates: LineCandidate[];
  comments: string[];
  warnings: string[];
}

export interface ParsedOrderDraft {
  erp_order_number?: string | null;
  customer?: string | null;
  customer_rut?: string | null;
  order_date?: string | null;
  doc_type?: string | null; // "cotizacion" | "pedido" | ...
  source: string;
  lines: ParsedOrderLine[];
  document_warnings: string[];
}

export interface PickingLine {
  product_id: string;
  sku: string;
  name: string;
  barcode_expected: string[];
  quantity_required: number;
  quantity_picked: number;
  suggested_location_id?: string;
  status?: string;
}

export interface PickingTask {
  id: string;
  order_id: string;
  erp_order_number?: string;
  assigned_to?: string;
  warehouse_id?: string;
  status: string;
  lines: PickingLine[];
}

export interface PackageItem {
  product_id?: string;
  sku?: string;
  name?: string;
  quantity?: number;
}

export interface PackageBulto {
  package_id: string;
  label?: string;
  items: PackageItem[];
  public_token?: string;
  public_expires_at?: string;
}

// Vista pública del bulto (página del QR).
export interface PublicBultoItem {
  sku: string;
  name?: string | null;
  quantity: number;
}

export interface PublicBultoView {
  order_number?: string | null;
  customer?: string | null;
  package_label?: string | null;
  package_number: number;
  package_count: number;
  items: PublicBultoItem[];
  total_units: number;
  item_count: number;
  packed_at?: string | null;
  dispatch: {
    dispatched: boolean;
    carrier?: string | null;
    tracking_number?: string | null;
    dispatch_date?: string | null;
  };
}

export interface PackingLine {
  product_id: string;
  sku: string;
  name: string;
  barcode_expected?: string[];
  quantity_required: number;
  quantity_packed: number;
  status?: string;
}

export interface PackingTask {
  id: string;
  order_id: string;
  picking_task_id?: string;
  assigned_to?: string;
  status: string;
  packages: PackageBulto[];
  lines: PackingLine[];
}

export interface Dispatch {
  id: string;
  order_id: string;
  status: string;
  carrier?: string;
  tracking_number?: string;
}

export interface SyncJob {
  id: string;
  erp: string;
  job_type: string;
  status: string;
  attempts: number;
  max_attempts: number;
  next_retry_at?: string;
  last_error?: string;
  created_at: string;
}

export interface DefontanaStatus {
  status: string;
  environment?: string;
  mock?: boolean;
  last_check_at?: string;
  last_error?: string;
}

export interface ScanResult {
  status: 'ok' | 'rejected' | string;
  feedback?: 'complete' | 'partial' | 'warning' | 'error' | string;
  message?: string;
  line?: PickingLine | PackingLine | unknown;
  task?: PickingTask | PackingTask | unknown;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: User;
}
