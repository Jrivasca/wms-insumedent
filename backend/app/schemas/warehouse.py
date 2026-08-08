from typing import Optional

from pydantic import BaseModel

from app.models.location import LocationType
from app.models.warehouse import WarehouseType


class WarehouseCreate(BaseModel):
    name: str
    erp_storage_code: Optional[str] = None
    description: Optional[str] = None
    type: WarehouseType = WarehouseType.WMS_WAREHOUSE
    sale_available: bool = True


class LocationCreate(BaseModel):
    warehouse_id: str
    code: str
    name: Optional[str] = None
    zone: Optional[str] = None
    aisle: Optional[str] = None
    rack: Optional[str] = None
    level: Optional[str] = None
    bin: Optional[str] = None
    type: LocationType = LocationType.STORAGE


class LocationUpdate(BaseModel):
    """Partial update of a location. The warehouse is intentionally not editable
    (stock balances and picking tasks reference the location by id within it)."""

    code: Optional[str] = None
    name: Optional[str] = None
    zone: Optional[str] = None
    aisle: Optional[str] = None
    rack: Optional[str] = None
    level: Optional[str] = None
    bin: Optional[str] = None
    type: Optional[LocationType] = None
    is_active: Optional[bool] = None
