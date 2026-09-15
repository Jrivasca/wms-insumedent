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

export type NotificationType =
  | 'order_created'
  | 'order_dispatched'
  | 'stock_zero'
  | 'receipt_unblocks_order'
  | string;

export interface AppNotification {
  id: string;
  type: NotificationType;
  title: string;
  body: string;
  entity_type?: string | null;
  entity_id?: string | null;
  metadata?: Record<string, unknown>;
  read_at?: string | null;
  created_at: string;
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
  cost?: number;
  sale_price?: number;
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
    despacho_parcial: number;
    despachados: number;
    despachados_hoy: number;
    error_cancelados: number;
    parciales: number;
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
  | 'partially_dispatched'
  | 'dispatched'
  | 'cancelled'
  | string;

export type OrderFulfillment = 'complete' | 'partial' | string;

export interface OrderLine {
  line_id: string;
  product_id: string;
  sku: string;
  name: string;
  unit?: string;
  ordered_quantity: number;
  picked_quantity: number;
  packed_quantity: number;
  dispatched_quantity?: number;
  status?: string;
}

export interface Order {
  id: string;
  erp_order_number: string;
  customer: string;
  status: OrderStatus;
  fulfillment?: OrderFulfillment;
  order_date?: string;
  delivery_date?: string;
  lines: OrderLine[];
  /** Estado del pedido en Defontana (p. ej. "EEX (EN_DESPACHO_EN_FACTURACION)"). */
  erp_status?: string | null;
  /** Cambió en Defontana mientras estaba en preparación: requiere revisión. */
  erp_attention?: { reason: string; erp_status?: string; detected_at?: string } | null;
  cancel_reason?: string | null;
}

/** Lote informado por Defontana (referencia; no mueve stock del WMS). */
export interface ErpStockLot {
  lot_number: string;
  stock: number;
  expiration_date?: string | null;
}

/** Stock de Defontana vs stock del WMS para un SKU en una bodega. */
export interface ErpStockRow {
  sku: string;
  name?: string | null;
  storage_code: string;
  erp_stock: number | null;
  erp_reserved: number | null;
  erp_to_receive: number | null;
  wms_stock: number;
  difference: number;
  in_erp: boolean;
  in_wms_catalog: boolean;
  erp_lots: ErpStockLot[];
}

export interface ErpStockComparison extends Page<ErpStockRow> {
  summary: {
    rows: number;
    with_difference: number;
    erp_only: number;
    wms_only: number;
    snapshot_at?: string | null;
    unmapped_warehouses: string[];
    unknown_storage_codes: string[];
  };
}

/** Línea corta de un pedido parcial cuyo faltante ya está cubierto por stock. */
export interface CompletableOrderLine {
  line_id: string;
  product_id: string;
  sku: string;
  name: string;
  missing: number;
  available: number;
}

/** Pedido parcial que ya se puede completar (llegó stock para alguna línea corta). */
export interface CompletableOrder {
  order_id: string;
  erp_order_number: string;
  customer?: string | null;
  status: OrderStatus;
  warehouse_id: string;
  lines: CompletableOrderLine[];
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
  erp_order_number?: string | null;
  picking_task_id?: string;
  assigned_to?: string;
  status: string;
  packages: PackageBulto[];
  lines: PackingLine[];
}

export interface DispatchLine {
  line_id?: string;
  product_id?: string | null;
  sku: string;
  quantity: number;
}

export interface Dispatch {
  id: string;
  order_id: string;
  status: string;
  guide_number?: string;
  carrier?: string;
  tracking_number?: string;
  lines?: DispatchLine[];
  package_ids?: string[];
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
  configured?: boolean;
  environment?: string;
  auth_mode?: string;
  base_url?: string;
  /** Identificadores guardados (solo supervisores). La contraseña nunca viaja: solo si existe. */
  credentials?: {
    client?: string | null;
    company?: string | null;
    user?: string | null;
    email?: string | null;
    has_password: boolean;
    has_email_password: boolean;
  };
  /** Última foto de stock traída de Defontana (Inventory/GetFutureStockInfo). */
  last_stock_sync_at?: string | null;
  orders_auto_sync?: {
    enabled: boolean;
    interval_minutes: number;
    hours: string;
    weekdays_only: boolean;
    last_run_at?: string | null;
    last_summary?: Record<string, number> | null;
    last_error?: string | null;
  };
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
