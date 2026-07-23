export type Role = 'admin' | 'supervisor' | 'picker' | 'packer' | 'operario' | string;

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
  message?: string;
  line?: PickingLine | PackingLine | unknown;
  task?: PickingTask | PackingTask | unknown;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: User;
}
