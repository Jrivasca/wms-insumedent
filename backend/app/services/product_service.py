from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from app.core.config import settings
from app.core.database import get_database
from app.core.utils import now_utc, serialize, to_object_id
from app.models import Collections
from app.models.product import BarcodeSource, BarcodeType
from app.models.sync_job import SyncJobType
from app.services import sync_job_service


async def _barcodes_for(tenant_id: str, product_id: str) -> List[Dict[str, Any]]:
    db = get_database()
    cursor = db[Collections.BARCODES].find(
        {"tenant_id": tenant_id, "product_id": product_id, "is_active": True}
    )
    return [
        {"barcode": b["barcode"], "type": b.get("type")}
        for b in await cursor.to_list(length=100)
    ]


async def list_products(
    tenant_id: str,
    search: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    db = get_database()
    query: Dict[str, Any] = {"tenant_id": tenant_id}
    if search:
        query["$or"] = [
            {"sku": {"$regex": search, "$options": "i"}},
            {"name": {"$regex": search, "$options": "i"}},
        ]
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    cursor = (
        db[Collections.PRODUCTS].find(query).sort("name", 1).skip(offset).limit(limit)
    )
    result = []
    for p in await cursor.to_list(length=limit):
        data = serialize(p)
        data["barcodes"] = await _barcodes_for(tenant_id, data["id"])
        result.append(data)
    return result


async def get_product(tenant_id: str, product_id: str) -> Dict[str, Any]:
    db = get_database()
    product = await db[Collections.PRODUCTS].find_one(
        {"_id": to_object_id(product_id), "tenant_id": tenant_id}
    )
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    data = serialize(product)
    data["barcodes"] = await _barcodes_for(tenant_id, data["id"])
    return data


async def get_by_barcode(tenant_id: str, barcode: str) -> Dict[str, Any]:
    db = get_database()
    bc = await db[Collections.BARCODES].find_one(
        {"tenant_id": tenant_id, "barcode": barcode, "is_active": True}
    )
    if not bc:
        # Fall back to SKU lookup so operators can scan an internal code.
        product = await db[Collections.PRODUCTS].find_one(
            {"tenant_id": tenant_id, "sku": barcode}
        )
        if not product:
            raise HTTPException(status_code=404, detail="No product for this barcode")
    else:
        product = await db[Collections.PRODUCTS].find_one(
            {"_id": to_object_id(bc["product_id"]), "tenant_id": tenant_id}
        )
        if not product:
            raise HTTPException(status_code=404, detail="Product not found for barcode")

    data = serialize(product)
    data["barcodes"] = await _barcodes_for(tenant_id, data["id"])
    data["matched_barcode"] = barcode
    return data


async def add_barcode(
    tenant_id: str, product_id: str, barcode: str, barcode_type: str, actor: str
) -> Dict[str, Any]:
    db = get_database()
    product = await db[Collections.PRODUCTS].find_one(
        {"_id": to_object_id(product_id), "tenant_id": tenant_id}
    )
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    existing = await db[Collections.BARCODES].find_one(
        {"tenant_id": tenant_id, "barcode": barcode}
    )
    if existing:
        raise HTTPException(status_code=409, detail="Barcode already exists for this tenant")

    now = now_utc()
    doc = {
        "tenant_id": tenant_id,
        "product_id": product_id,
        "barcode": barcode,
        "type": barcode_type,
        "source": BarcodeSource.MANUAL.value,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
        "created_by": actor,
    }
    result = await db[Collections.BARCODES].insert_one(doc)
    doc["_id"] = result.inserted_id
    return serialize(doc)


async def create_product(
    tenant_id: str, data: Dict[str, Any], actor: str, sync_erp: bool = True
) -> Dict[str, Any]:
    """Create a product in the WMS and (optionally) enqueue an ERP sync job.

    SKU is unique per tenant. If a ``barcode`` is provided it is attached. The ERP
    sync is best-effort and asynchronous (see SyncJobType.CREATE_PRODUCT).
    """
    db = get_database()
    sku = (data.get("sku") or "").strip()
    if not sku:
        raise HTTPException(status_code=400, detail="SKU es obligatorio")

    existing = await db[Collections.PRODUCTS].find_one({"tenant_id": tenant_id, "sku": sku})
    if existing:
        raise HTTPException(status_code=409, detail="Ya existe un producto con ese SKU")

    now = now_utc()
    doc = {
        "tenant_id": tenant_id,
        "erp_product_id": f"WMS-{sku}",
        "sku": sku,
        "name": data.get("name") or sku,
        "description": data.get("description") or data.get("name") or sku,
        "unit": data.get("unit") or "UN",
        "brand": data.get("brand"),
        "category": data.get("category") or "Sin categoría",
        "uses_lots": bool(data.get("uses_lots")),
        "uses_serials": bool(data.get("uses_serials")),
        "is_service": bool(data.get("is_service")),
        "is_active": True,
        "cost": data.get("cost"),
        "sale_price": data.get("sale_price"),
        "raw_erp_data": None,
        "created_at": now,
        "updated_at": now,
        "created_by": actor,
    }
    result = await db[Collections.PRODUCTS].insert_one(doc)
    product_id = str(result.inserted_id)

    barcode = (data.get("barcode") or "").strip()
    if barcode:
        bc_type = BarcodeType.EAN13.value if barcode.isdigit() and len(barcode) == 13 else BarcodeType.INTERNAL.value
        await add_barcode(tenant_id, product_id, barcode, bc_type, actor)

    if sync_erp and settings.erp_sync_enabled:
        await sync_job_service.enqueue(
            tenant_id=tenant_id,
            job_type=SyncJobType.CREATE_PRODUCT.value,
            payload={
                "product_id": product_id,
                "Code": sku,
                "Name": doc["name"],
                "Unit": doc["unit"],
                "Family": doc["category"],
                "BarCode": barcode or None,
            },
            created_by=actor,
        )

    return await get_product(tenant_id, product_id)
