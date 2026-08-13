"""Domain models and collection name constants for the WMS."""


class Collections:
    TENANTS = "tenants"
    USERS = "users"
    ERP_CONNECTIONS = "erp_connections"
    ERP_TOKENS = "erp_tokens"
    PRODUCTS = "products"
    BARCODES = "barcodes"
    WAREHOUSES = "warehouses"
    LOCATIONS = "locations"
    INVENTORY_BALANCES = "inventory_balances"
    INVENTORY_MOVEMENTS = "inventory_movements"
    ORDERS = "orders"
    PICKING_TASKS = "picking_tasks"
    PACKING_TASKS = "packing_tasks"
    DISPATCHES = "dispatches"
    SYNC_JOBS = "sync_jobs"
    AUDIT_LOGS = "audit_logs"
    INTEGRATION_LOGS = "integration_logs"
    NOTIFICATIONS = "notifications"
    # Edge-trigger state for stock-zero alerts (one row per product+warehouse).
    STOCK_ALERTS = "stock_alerts"
    # Web Push (VAPID) browser subscriptions, one per user+device endpoint.
    PUSH_SUBSCRIPTIONS = "push_subscriptions"
    # Folder-watch order intake (Plan 1 Fase 1): review queue for parsed PDFs that
    # need a human before becoming an order, and a log of processed files.
    ORDER_IMPORT_DRAFTS = "order_import_drafts"
    INTAKE_RUNS = "intake_runs"
    # Excel catalog import (Plan 1 Fase 2): per-tenant last-import state for the
    # "no lo cargaste en 24 h" staleness reminder.
    CATALOG_IMPORT_STATE = "catalog_import_state"
    # Near-expiry alert dedupe (Plan 1 Fase 5): one row per product+warehouse+lot.
    EXPIRY_ALERTS = "expiry_alerts"
