from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from app.core.database import get_database
from app.core.utils import now_utc, serialize, to_object_id
from app.models import Collections
from app.models.product import BarcodeSource


async def _barcodes_for(tenant_id: str, product_id: str) -> List[Dict[str, Any]]:
    db = get_database()
    cursor = db[Collections.BARCODES].find(
        {"tenant_id": tenant_id, "product_id": product_id, "is_active": True}
    )
    return [
        {"barcode": b["barcode"], "type": b.get("type")}
        for b in await cursor.to_list(length=100)
    ]


async def list_products(tenant_id: str, search: Optional[str] = None) -> List[Dict[str, Any]]:
    db = get_database()
    query: Dict[str, Any] = {"tenant_id": tenant_id}
    if search:
        query["$or"] = [
            {"sku": {"$regex": search, "$options": "i"}},
            {"name": {"$regex": search, "$options": "i"}},
        ]
    products = await db[Collections.PRODUCTS].find(query).sort("name", 1).to_list(length=500)
    result = []
    for p in products:
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
