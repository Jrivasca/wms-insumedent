from enum import Enum


class WarehouseType(str, Enum):
    ERP_STORAGE = "erp_storage"
    WMS_WAREHOUSE = "wms_warehouse"
